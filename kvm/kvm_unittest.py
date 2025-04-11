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
from avocado.utils import git
from avocado.utils import build, process, genio
from avocado.utils import linux_modules

# pylint: disable=too-many-instance-attributes
class KVMUnitTests(Test):
    """
    Avocado test suite for validating KVM functionality.
    """

    def setUp(self):
        """
        Setup steps for the test:
        - Clone the KVM unit tests repository if not already present.
        - Build the KVM unit tests for the specified architecture and QEMU.
        - Check and configure the appropriate KVM module (kvm_amd or kvm_intel).
        """
        self.kvm_tests_repo = self.params.get(
            "kvm_tests_repo",
            default="https://github.com/kvm-unit-tests/kvm-unit-tests.git",
        )
        self.kvm_tests_dir = os.path.join(self.teststmpdir, "kvm-unit-tests")
        self.tests = self.params.get("test", default="x2apic")
        self.mode = self.params.get("mode", default=None)
        self.kvm_module = self.params.get(
            "kvm_module", default=self.detect_kvm_module()
        )
        self.kvm_param_state = self.params.get("kvm_param_state", default="avic")
        self.arch = self.params.get("target_arch", default="x86_64")
        self.cross_prefix = self.params.get("cross_prefix", default=None)
        self.qemu_binary = self.params.get("qemu_binary", default=None)
        self.initial_dmesg = "dmesg_initial.txt"
        self.final_dmesg = "dmesg_final.txt"
        self.env = os.environ.copy()

        if not os.path.exists(self.kvm_tests_dir):
            self.log.info("Clone the kvm-unit-test repository: %s", self.kvm_tests_repo)
            git.get_repo(self.kvm_tests_repo, destination_dir=self.kvm_tests_dir)

        if self.qemu_binary is not None:
            self.env["QEMU"] = self.qemu_binary

        self.log.info("Build kvm-unit-test")
        os.chdir(self.kvm_tests_dir)
        configure_cmd = f"./configure --arch={self.arch}"
        if self.cross_prefix:
            configure_cmd += f" --cross-prefix={self.cross_prefix}"
        process.system(configure_cmd, env=self.env, ignore_status=True, shell=True)
        build.make(self.kvm_tests_dir, extra_args=f"-j{os.cpu_count()}")

        kernel_config_option = f"CONFIG_{self.kvm_module.upper()}"
        self.check_kvm_module_config(kernel_config_option)

    def detect_kvm_module(self):
        """
        Detects the appropriate KVM module based on the CPU vendor.
        Defaults to 'kvm_amd' if AMD CPU, 'kvm_intel' if Intel CPU.
        """
        cpu_info = genio.read_file("/proc/cpuinfo")
        if "AuthenticAMD" in cpu_info:
            return "kvm_amd"
        if "GenuineIntel" in cpu_info:
            return "kvm_intel"
        self.log.warning(
            "CPU vendor not detected. Using default 'kvm_amd'. Set 'kvm_module' to override."
        )
        return "kvm_amd"

    def check_kvm_module_config(self, config_option):
        """
        Check if the specified kernel module is enabled in the kernel configuration.
        :param config_option: check kernel config option (e.g., CONFIG_KVM_AMD or CONFIG_KVM_INTEL)
        """
        config_status = linux_modules.check_kernel_config(config_option)

        if config_status == linux_modules.ModuleConfig.NOT_SET:
            self.cancel(f"{config_option} is not set. Cancelling test.")

        elif config_status == linux_modules.ModuleConfig.MODULE:
            self.log.info("%s is configured as a module.", config_option)
            self.configure_kvm_module()

        elif config_status == linux_modules.ModuleConfig.BUILTIN:
            self.log.info("%s is built-in.", config_option)
            if self.mode is not None:
                expected_value = (
                    ("1", "Y") if self.mode == "accelerated" else ("0", "N")
                )

                if not self.check_kvm_module_param(expected_value):
                    self.cancel(f"Cannot modify parameter: {config_option} is built-in.")
            else:
                self.log.info(
                    "AVIC-specific mode is not set; skipping the KVM parameter validation."
                )

    def configure_kvm_module(self):
        """
        Configure the specified KVM module based on the test mode.
        - Loads the module with the parameter enabled for accelerated mode.
        - Loads the module with the parameter disabled for non-accelerated mode.
        """
        self.log.info("Unloading existing module '%s' (if loaded).", self.kvm_module)
        linux_modules.unload_module(self.kvm_module)

        if self.mode == "accelerated":
            process.run(
                f"dmesg -T > {self.initial_dmesg}", shell=True, ignore_status=True
            )
            self.log.info(
                "Configuring for accelerated mode: Loading module '%s' with parameter '%s=1'.",
                self.kvm_module,
                self.kvm_param_state,
            )

            linux_modules.load_module(f"{self.kvm_module} {self.kvm_param_state}=1")

            process.run(
                f"dmesg -T > {self.final_dmesg}", shell=True, ignore_status=True
            )

            expected_value = ("1", "Y")
            if not self.check_kvm_module_param(expected_value):
                self.cancel(
                    f"Cannot set module {self.kvm_module} parameter {self.kvm_param_state} to 1."
                )
            self.validate_kvm_dmesg()

        elif self.mode == "non-accelerated":
            self.log.info(
                "Configuring for non-accelerated mode: Loading module '%s' with parameter '%s=0'.",
                self.kvm_module,
                self.kvm_param_state,
            )

            linux_modules.load_module(f"{self.kvm_module} {self.kvm_param_state}=0")

            expected_value = ("0", "N")
            if not self.check_kvm_module_param(expected_value):
                self.cancel(
                    f"Cannot set module {self.kvm_module} parameter {self.kvm_param_state} to 0."
                )

        elif self.mode is None:
            if not linux_modules.module_is_loaded(self.kvm_module):
                self.log.info(
                    "KVM kernel module '%s' is not loaded. Loading...", self.kvm_module
                )
                linux_modules.load_module(self.kvm_module)
        else:
            self.cancel(
                f"Unsupported mode '{self.mode}'. Use 'accelerated' or 'non-accelerated'."
            )

    def check_kvm_module_param(self, expected_value):
        """
        Check the value of /sys/module/{kvm_module}/parameters/{self.kvm_param_state}
        """
        param_path = f"/sys/module/{self.kvm_module}/parameters/{self.kvm_param_state}"
        if not os.path.exists(param_path):
            self.cancel(f"Module parameter file not found: {param_path}.")

        status = genio.read_file(param_path).rstrip("\n")
        if status not in expected_value:
            return False
        return True

    def validate_kvm_dmesg(self):
        """
        Check AVIC and x2AVIC status in dmesg logs diff.
        """
        cmd = f"diff {self.initial_dmesg} {self.final_dmesg}"
        diff = process.run(cmd, ignore_status=True, shell=True).stdout_text

        # Check for the "avic enabled" in dmesg (must be present in accelerated mode)
        if "AVIC enabled" not in diff:
            self.cancel(f"AVIC not enabled after loading {self.kvm_module} with avic=1")

        # Check for the "x2avic enabled" only if the test is "x2apic"
        if ("x2AVIC enabled" not in diff) and (self.tests == "x2apic"):
            self.cancel(
                f"x2AVIC not enabled after loading {self.kvm_module} with avic=1."
            )

    def test(self):
        """
        Run the specified KVM unit tests using the run_tests.sh script.
        Capture and analyze the output to determine success, failure, or skip status.
        """
        self.log.info("Running test: %s", self.tests)
        try:
            os.chdir(self.kvm_tests_dir)
            result = process.run(
                f"./run_tests.sh {self.tests} ", shell=True, verbose=True, env=self.env
            ).stdout_text

            process.run(f"cat logs/{self.tests}.log", shell=True, ignore_status=True)
            shutil.copy(f"logs/{self.tests}.log", self.outputdir)

            if "FAIL" in result:
                self.fail(" ".join(result.split()[2:]))
            elif "SKIP" in result:
                self.log.warn(f"Test {self.tests} was skipped. Output: {result}")

        except process.CmdError as e:
            self.fail(f"Test {self.tests} encountered an error: {e}")

    def tearDown(self):
        """
        Cleanup steps after the test.
        - Unload the kvm module.
        - Remove the cloned KVM unit tests repository.
        """
        self.log.info("Initiating unload of module: %s", self.kvm_module)
        if linux_modules.module_is_loaded(self.kvm_module):
            linux_modules.unload_module(self.kvm_module)

        if os.path.exists(self.kvm_tests_dir):
            self.log.info("Removing KVM unit tests repository")
            process.run(f"rm -rf {self.kvm_tests_dir}", shell=True, ignore_status=True)
