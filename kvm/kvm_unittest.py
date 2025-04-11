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


class KVMUnitTests(Test):
    """
    Avocado test suite for validating KVM functionality.
    """

    def setUp(self):
        """
        Setup steps for the test.
                - Clone the KVM unit tests repository if not already present.
                - Build the KVM unit tests.
                - Check CONFIG_KVM_AMD and configure the kvm_amd module.
        """
        self.kvm_tests_repo = self.params.get(
            "kvm_tests_repo",
            default="https://github.com/kvm-unit-tests/kvm-unit-tests.git",
        )
        self.kvm_tests_dir = os.path.join(self.teststmpdir, "kvm-unit-tests")
        self.tests = self.params.get("test", default="x2apic")
        self.mode = self.params.get("mode", default="non-accelerated")
        self.initial_dmesg = "dmesg_initial.txt"
        self.final_dmesg = "dmesg_final.txt"

        if not os.path.exists(self.kvm_tests_dir):
            self.log.info(
                "Clone the kvm-unit-test repository: %s", {self.kvm_tests_repo}
            )
            git.get_repo(self.kvm_tests_repo, destination_dir=self.kvm_tests_dir)

        # Build the tests using avocado.utils.build
        self.log.info("Build kvm-unit-test")
        os.chdir(self.kvm_tests_dir)
        process.system("./configure", ignore_status=True, shell=True)
        build.make(self.kvm_tests_dir)

        # Check and configure kvm_amd module
        self.check_kvm_amd_module()

    def check_kvm_amd_module(self):
        """
        Check if CONFIG_KVM_AMD is enabled in the kernel configuration.
        """
        config_status = linux_modules.check_kernel_config("CONFIG_KVM_AMD")

        if config_status == linux_modules.ModuleConfig.NOT_SET:
            self.log.info("CONFIG_KVM_AMD is not set.")
            self.cancel("CONFIG_KVM_AMD is not set. Cancelling test.")
        elif config_status == linux_modules.ModuleConfig.MODULE:
            self.log.info("CONFIG_KVM_AMD is set as a module.")
            self.configure_kvm_amd_module()
        elif config_status == linux_modules.ModuleConfig.BUILTIN:
            self.log.info("CONFIG_KVM_AMD is built-in.")
            if (
                self.mode == "accelerated" and not self.check_kvm_amd_avic(("1", "Y"))
            ) or (
                self.mode == "non-accelerated"
                and not self.check_kvm_amd_avic(("0", "N"))
            ):
                self.cancel(
                    "CONFIG_KVM_AMD is built-in and kvm_amd module parameter cannot be changed."
                )

    def configure_kvm_amd_module(self):
        """
        Configure the system based on the mode.
        - Load kvm_amd with AVIC enabled for accelerated mode.
        - Load kvm_amd with AVIC disabled for non-accelerated mode.
        """
        linux_modules.unload_module("kvm_amd")

        if self.mode == "accelerated":
            process.run(
                f"dmesg -T > {self.initial_dmesg}", shell=True, ignore_status=True
            )
            self.log.info(
                "Configuring for accelerated mode: Loading kvm_amd with avic=1"
            )

            # Load kvm_amd with avic=1 for accelerated mode
            linux_modules.load_module("kvm_amd avic=1")

            process.run(
                f"dmesg -T > {self.final_dmesg}", shell=True, ignore_status=True
            )

            expected_value = ("1", "Y")
            if not self.check_kvm_amd_avic(expected_value):
                self.cancel("Cannot set module kvm_amd parameter avic to 1.")
            self.check_dmesg_avic()

        elif self.mode == "non-accelerated":
            self.log.info(
                "Configuring for non-accelerated mode: Loading kvm_amd with avic=0"
            )

            # Load kvm_amd with avic=0 for non-accelerated mode
            linux_modules.load_module("kvm_amd avic=0")

            expected_value = ("0", "N")
            if not self.check_kvm_amd_avic(expected_value):
                self.cancel("Cannot set module kvm_amd parameter avic to 0.")

        else:
            self.cancel(f"Unsupported mode '{self.mode}'. Use 'accelerated' or 'non-accelerated'.")

    def check_kvm_amd_avic(self, expected_value):
        """
        Check the value of /sys/module/kvm_amd/parameters/avic
        """
        if not os.path.exists("/sys/module/kvm_amd/parameters/avic"):
            self.cancel("kvm_amd module is not loaded.")
        avic_value = genio.read_file("/sys/module/kvm_amd/parameters/avic").rstrip("\n")
        if avic_value not in expected_value:
            return False
        return True

    def check_dmesg_avic(self):
        """
        Check AVIC and x2AVIC status in dmesg logs diff.
        """
        cmd = f"diff {self.initial_dmesg} {self.final_dmesg}"
        diff = process.run(cmd, ignore_status=True, shell=True).stdout_text

        # Check for the "avic enabled" in dmesg (must be present in accelerated mode)
        if "AVIC enabled" not in diff:
            self.cancel("AVIC not enabled after loading kvm_amd with avic=1")

        # Check for the "x2avic enabled" only if the test is "x2apic"
        if ("x2AVIC enabled" not in diff) and (self.tests == "x2apic"):
            self.cancel("x2AVIC not enabled after loading kvm_amd with avic=1.")

    def test(self):
        """
        Run the specified KVM unit tests using the run_tests.sh script.
        Capture and analyze the output to determine success, failure, or skip status.
        """
        self.log.info("Running test: %s", {self.tests})
        try:
            os.chdir(self.kvm_tests_dir)
            result = process.run(
                f"./run_tests.sh {self.tests}", shell=True, verbose=True
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
        - Unload the kvm_amd module.
        - Remove the cloned KVM unit tests repository.
        """
        self.log.info("Unloading kvm_amd module")
        linux_modules.unload_module("kvm_amd")

        if os.path.exists(self.kvm_tests_dir):
            self.log.info("Removing KVM unit tests repository")
            process.run(f"rm -rf {self.kvm_tests_dir}", shell=True, ignore_status=True)
