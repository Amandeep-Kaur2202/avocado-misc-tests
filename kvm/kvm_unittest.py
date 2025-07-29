#!/usr/bin/env python
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
#
# Copyright: 2025 Advanced Micro Devices, Inc.
# Author: Narasimhan V <narasimhan.v@amd.com>
# Author: Dheeraj Kumar Srivastava <dheerajkumar.srivastava@amd.com>
# Author: Amandeep Kaur Longia <amandeepkaur.longia@amd.com>

import os
import shutil

from avocado import Test
from avocado.utils import dmesg
from avocado.core.exceptions import TestSkipError
from avocado.utils import git, build, process, genio
from avocado.utils import cpu, linux_modules

# Map CPU vendors to their corresponding KVM kernel modules and kernel config options
KVM_MODULE_MAP = {
    "amd": ("kvm_amd", "CONFIG_KVM_AMD"),
    "intel": ("kvm_intel", "CONFIG_KVM_INTEL"),
    # Add new vendors here if needed.
}


def detect_kvm_module():
    """
    Detect CPU vendor and return the KVM kernel module and kernel configuration symbol.
    Returns:
        tuple: (module_name, kernel_config_option)
    Raises:
        TestSkipError: If CPU vendor cannot be determined or no mapping exists.
    """
    try:
        vendor = cpu.get_vendor()
        if not vendor:
            raise ValueError("Unable to determine CPU vendor.")
        vendor = vendor.lower()
        if vendor in KVM_MODULE_MAP:
            return KVM_MODULE_MAP[vendor]
        raise ValueError(f"No KVM module mapping for CPU vendor: {vendor}")
    except Exception as e:
        raise TestSkipError(f"Failed to detect KVM module: {e}") from e


def capture_module_parameters(params_dir):
    """
    Capture current parameters of a loaded kernel module from sysfs.
    Args:
        params_dir (str): Path to the module's sysfs parameters directory.
    Returns:
        dict: Parameter names and their current values.
    Raises:
        TestSkipError: If parameters directory does not exist or reading fails.
    """
    if not os.path.exists(params_dir):
        raise TestSkipError(f"Sysfs parameters directory not found: {params_dir}")

    params = {}
    for param in os.listdir(params_dir):
        param_path = os.path.join(params_dir, param)
        if os.path.isfile(param_path) and os.access(param_path, os.R_OK):
            try:
                # Assumes parameters are text files.
                value = genio.read_file(param_path).rstrip("\n")
                params[param] = value
            except (OSError, IOError) as exc:
                raise TestSkipError(
                    f"Failed to read parameter '{param}': {exc}"
                ) from exc

    return params


def verify_sysfs_param(file_path, expected_values):
    """
    Verify if a sysfs parameter file's value matches one of the expected values.
    Args:
        file_path (str): Path to the sysfs parameter file.
        expected_values (tuple or list): Allowed values.
    Returns:
        bool: True if current value matches one of expected values, False otherwise.
    """
    if not os.path.exists(file_path):
        return False

    try:
        current_value = genio.read_file(file_path).rstrip("\n")
        return current_value in expected_values
    except (OSError, IOError):
        # Propagate exceptions for caller to handle.
        raise


# pylint: disable=too-many-instance-attributes
class KVMUnitTest(Test):
    """
    Avocado test suite to validate KVM functionality using kvm-unit-tests.
    """

    def setUp(self):
        """
        Set up the test environment:
        - Clone and build the kvm-unit-tests repository if not already present.
        - Detect and configure the vendor specific KVM module (eg: kvm_amd or kvm_intel).
        - Set environment variables to run the test.
        """
        self.init_parameters()

        if self.mode not in ("accelerated", "non-accelerated", None):
            self.cancel(
                f"Invalid mode '{self.mode}', expected 'accelerated', 'non-accelerated', or empty"
            )

        # Setup QEMU binary in test environment, if specified
        if self.qemu_binary:
            if os.path.exists(self.qemu_binary):
                self.test_env["QEMU"] = self.qemu_binary
            else:
                self.cancel(f"Custom QEMU binary not found: {self.qemu_binary}")

        # Set accelerator in test environment, if specified in parameters.
        if self.accelerator:
            self.test_env["ACCEL"] = self.accelerator

        # Detect KVM module and kernel config option
        try:
            self.kvm_module, self.config_option = detect_kvm_module()
        except TestSkipError as e:
            self.cancel(str(e))

        self.file_path = (
            f"/sys/module/{self.kvm_module}/parameters/{self.kvm_module_param}"
        )
        self.capture_kvm_module_state()
        self.check_and_configure_kvm_module()

        # Clone the KVM unit tests repository, if needed
        if not os.path.isdir(self.kvm_tests_dir):
            git.get_repo(self.kvm_tests_repo, destination_dir=self.kvm_tests_dir)

        # Build the KVM unit tests repository
        os.chdir(self.kvm_tests_dir)
        build_status = os.path.join(self.kvm_tests_dir, ".kvm_build_status")
        rebuild_required = not (
            os.path.exists(build_status)
            and open(build_status, "r", encoding="utf-8").read().strip() == "success"
        )

        if not rebuild_required:
            self.log.info("KVM unit test repository already built. Skipping rebuild.")
        else:
            self.log.info(
                "KVM unit test repository build failed or not found. Rebuilding."
            )
            try:
                process.system(
                    f"./configure {self.configure_args}",
                    ignore_status=False,
                    shell=True,
                )
                build.make(self.kvm_tests_dir, extra_args=f"-j {os.cpu_count()}")
                with open(build_status, "w", encoding="utf-8") as f:
                    f.write("success")
            except Exception as err:
                with open(build_status, "w", encoding="utf-8") as f:
                    f.write("failed")
                self.log.error("Failed to build kvm-unit-tests: %s", err)
                raise

        # If no tests specified, list all available tests
        if self.tests == "":
            self.tests = " ".join(
                process.run(
                    "./run_tests.sh -l", shell=True, verbose=True
                ).stdout_text.split()
            )

    def init_parameters(self):
        """
        Initialize test configuration parameters and runtime environment.
        """
        self.kvm_tests_repo = self.params.get(
            "kvm_tests_repo",
            default="https://gitlab.com/kvm-unit-tests/kvm-unit-tests",
        )
        self.kvm_tests_dir = os.path.join(self.teststmpdir, "kvm-unit-tests")
        self.configure_args = self.params.get("configure_args", default="")
        self.tests = self.params.get("test", default="")
        self.mode = self.params.get("mode", default=None)
        self.qemu_binary = self.params.get("qemu_binary")
        self.accelerator = self.params.get("accelerator")
        self.kvm_module = None
        self.kvm_module_param = self.params.get("kvm_module_param", default="avic")
        self.test_env = os.environ.copy()
        self.initial_kvm_params = {}
        self.initial_dmesg = os.path.join(self.teststmpdir, "dmesg_initial.txt")
        self.final_dmesg = os.path.join(self.teststmpdir, "dmesg_final.txt")


    def capture_kvm_module_state(self):
        """
        Stores the initial state and readable parameters of the KVM module.
        - If the module is not loaded, save the state as 'unloaded'.
        - If the module is loaded, save the state as 'loaded'; read and store sysfs parameters.
        """
        if not linux_modules.module_is_loaded(self.kvm_module):
            self.initial_kvm_params["__state__"] = "unloaded"
            return

        kvm_sysfs_param_dir = f"/sys/module/{self.kvm_module}/parameters"

        try:
            self.log.info(
                "Storing initial values for KVM module '%s'.", self.kvm_module
            )
            self.initial_kvm_params = capture_module_parameters(kvm_sysfs_param_dir)
            self.initial_kvm_params["__state__"] = "loaded"
        except TestSkipError as e:
            self.cancel(str(e))

    def check_and_configure_kvm_module(self):
        """
        Check if the specified kernel config "config_option" is builtin, module or not set.
        """
        config_status = linux_modules.check_kernel_config(self.config_option)
        if config_status == linux_modules.ModuleConfig.NOT_SET:
            self.cancel(f"{self.config_option} is not set in the kernel configuration.")

        if config_status == linux_modules.ModuleConfig.MODULE:
            self.log.info("%s is a loadable kernel module.", self.config_option)
            self.configure_kvm_module()
            return

        if (
            config_status == linux_modules.ModuleConfig.BUILTIN
            and self.mode is not None
        ):
            self.log.info("%s is built-in kernel module.", self.config_option)
            expected_value = ("1", "Y") if self.mode == "accelerated" else ("0", "N")

            if not verify_sysfs_param(self.file_path, expected_value):
                self.cancel(
                    f"Cannot modify kvm module parameters since {self.config_option} is built-in."
                )

    def configure_kvm_module(self):
        """
        Configure the kvm module with appropriate parameter based on test mode
        Modes:
        - 'accelerated': Enables hardware acceleration by setting the module parameter to 1.
        - 'non-accelerated': Disables hardware acceleration by setting the module parameter to 0.
        - None: Loads the module without modifying the parameter.
        """
        if self.mode is None:
            if not linux_modules.module_is_loaded(self.kvm_module):
                linux_modules.load_module(self.kvm_module)
            return

        if linux_modules.module_is_loaded(self.kvm_module):
            linux_modules.unload_module(self.kvm_module)

        if self.mode == "accelerated":
            process.run(
                f"dmesg -T > {self.initial_dmesg}", shell=True, ignore_status=True
            )
            # Load module with parameter set to enable acceleration
            linux_modules.load_module(f"{self.kvm_module} {self.kvm_module_param}=1")
            process.run(
                f"dmesg -T > {self.final_dmesg}", shell=True, ignore_status=True
            )

            if not verify_sysfs_param(self.file_path, ("1", "Y")):
                self.cancel(
                    f"Failed to set '{self.kvm_module_param}=1' for module '{self.kvm_module}'."
                )
            self.verify_kvm_dmesg()

        elif self.mode == "non-accelerated":
            # Load module with parameter set to disable acceleration
            linux_modules.load_module(f"{self.kvm_module} {self.kvm_module_param}=0")

            if not verify_sysfs_param(self.file_path, ("0", "N")):
                self.cancel(
                    f"Failed to set '{self.kvm_module_param}=0' for module '{self.kvm_module}'."
                )

    def verify_kvm_dmesg(self):
        """
        Validates AVIC and x2AVIC enablement via dmesg logs.
        """
        try:
            diff, _ = dmesg.collect_dmesg_diff(self.initial_dmesg, self.final_dmesg)
        except dmesg.DmesgError as e:
            self.cancel(f"Dmesg diff failed: {e}")

        # Check for "AVIC enabled" in the dmesg diff (required for accelerated mode)
        if "AVIC enabled" not in diff:
            self.cancel("AVIC not enabled; cancelling accelerated mode tests.")

        # Check for "x2AVIC enabled" only if the test mode is 'x2apic'
        if "x2apic" in self.tests.split() and "x2AVIC enabled" not in diff:
            self.tests = " ".join(
                test for test in self.tests.split() if test != "x2apic"
            )
            if self.tests == "":
                self.cancel(
                    "x2AVIC not enabled. Cancelling the 'x2apic' test in accelerated mode."
                )
            self.log.warn("x2AVIC not enabled. Removing 'x2apic' from test list.")

    def test(self):
        """
        Run KVM unit tests listed in `self.tests` using `run_tests.sh` and log results.
        Fails the test suite if any test fails or if execution encounters an error.
        """
        os.chdir(self.kvm_tests_dir)
        failed_tests, skipped_tests, passed_tests = [], [], []

        try:
            for test in self.tests.split():
                result = process.run(
                    f"./run_tests.sh {test}",
                    shell=True,
                    ignore_status=False,
                    verbose=True,
                    env=self.test_env,
                ).stdout_text

                # Parse test outcome from stdout
                if "FAIL" in result:
                    failed_tests.append(test)
                elif "SKIP" in result:
                    skipped_tests.append(test)
                elif "PASS" in result:
                    passed_tests.append(test)

                # Copy respective test log to output directory and log its contents
                log_path = os.path.join(self.kvm_tests_dir, "logs", f"{test}.log")
                if os.path.exists(log_path):
                    shutil.copy(log_path, self.outputdir)
                    with open(log_path, "r", encoding="utf-8") as f:
                        self.log.info("%s", f.read())

            # Log summary of results
            for test_list, label in [
                (failed_tests, "failed"),
                (skipped_tests, "skipped"),
                (passed_tests, "passed"),
            ]:
                if test_list:
                    self.log.info(
                        "%d test(s) %s: %s.", len(test_list), label, test_list
                    )

            if failed_tests:
                self.fail(f"{len(failed_tests)} test(s) failed: {failed_tests}.")

        except process.CmdError as err:
            self.fail(f"Test execution failed: {err}")

    def tearDown(self):
        """
        Restore the KVM module state by unloading or reloading with original parameters.
        """
        if not hasattr(self, "initial_kvm_params"):
            return

        self.log.info("Restoring the initial setup")

        if self.initial_kvm_params.get("__state__") == "unloaded":
            # Unload the module if currently loaded, as it was initially unloaded
            linux_modules.unload_module(self.kvm_module)

        elif self.initial_kvm_params.get("__state__") == "loaded":
            # Reload the module with original parameters
            param_args = " ".join(
                f"{k}={v}"
                for k, v in self.initial_kvm_params.items()
                if k != "__state__"
            )
            if param_args:
                linux_modules.unload_module(self.kvm_module)
                linux_modules.load_module(f"{self.kvm_module} {param_args}")
