import os
import shutil

from avocado import Test
from avocado.utils import build
from avocado.utils import process
from avocado.utils import git

class KVMUnitTests(Test):
    """
    Avocado test suite for validating KVM functionality.
    """

    def setUp(self):
        """
        Set up the test environment:
        - Clone the KVM unit tests repository.
        - Determine the test and mode to run from parameters.
        - Verify the kvm_amd module is loaded.
        - Store the original avic value and set the desired value.
        - Configure and build the KVM unit tests.
        """
        url = "https://gitlab.com/kvm-unit-tests/kvm-unit-tests.git"
        self.log.debug(f"Cloning repository from: {url} to: {self.teststmpdir}")
        git.get_repo(url, destination_dir=self.teststmpdir)
        self.sourcedir = self.teststmpdir
        self.log.debug(f"Source directory set to: {self.sourcedir}")

        self.test_to_run = self.params.get('test', default='x2apic')
        self.mode_to_run = self.params.get('mode', default='non-accelerated')
        self.accelerated = self.mode_to_run == 'accelerated'
        self.log.debug(f"Test to run: {self.test_to_run}, Mode to run: {self.mode_to_run}, Accelerated: {self.accelerated}")

        self.avic_path = "/sys/module/kvm_amd/parameters/avic"
        self.log.debug(f"Checking for avic path: {self.avic_path}")
        if not os.path.exists(self.avic_path):
            self.fail(f"System kernel does not have kvm_amd module loaded.")
        self.log.debug(f"avic path exists.")

        with open(self.avic_path, "r") as f:
            self.original_avic_value = f.read().strip()
        self.log.debug(f"Original avic value: {self.original_avic_value}")

        self._handle_avic_value(self.original_avic_value, self.accelerated)

        self.log.debug(f"Changing directory to: {self.sourcedir}")
        os.chdir(self.sourcedir)
        self.log.debug(f"Running configure command.")
        process.system('./configure', ignore_status=True, shell=True)
        self.log.debug(f"Running make command in: {self.sourcedir}")
        build.make(self.sourcedir)

    def _run_command(self, command, sudo=False, ignore_status=True, shell=True):
        """Helper function to run shell commands with consistent parameters."""
        self.log.debug(f"Running command: '{command}', sudo: {sudo}, ignore_status: {ignore_status}, shell: {shell}")
        return process.run(command, ignore_status=ignore_status, shell=shell, sudo=sudo)

    def _check_x2AVIC_support(self, initial_dmesg_file="dmesg_initial.txt", final_dmesg_file="dmesg_final.txt"):
        """Checks if x2AVIC is enabled by comparing dmesg output."""
        cmd = f"diff {initial_dmesg_file} {final_dmesg_file} | grep -i x2avic"
        result = self._run_command(cmd, ignore_status=True)
        is_enabled = "x2AVIC enabled" in result.stdout
        self.log.debug(f"Checking x2AVIC support. Diff output: '{result.stdout.strip()}', Enabled: {is_enabled}")
        return is_enabled

    def _handle_avic_value(self, original_avic_value, accelerated):
        """Handles setting the avic value and checking x2AVIC support."""
        initial_dmesg = "dmesg_initial.txt"
        final_dmesg = "dmesg_final.txt"

        self._run_command(f"dmesg -T > {initial_dmesg}", sudo=True)
        self._run_command("modprobe -r kvm_amd")

        avic_value = 1 if accelerated else 0
        self.log.debug(f"Setting avic value to: {avic_value}")
        self._run_command(f"modprobe kvm_amd avic={avic_value}")

        self._run_command(f"dmesg -T > {final_dmesg}", sudo=True)
        if not self._check_x2AVIC_support(initial_dmesg, final_dmesg) and accelerated:
            self.log.warning("x2AVIC was not enabled after setting avic=1.")

    def test(self):
        """
        Execute the specified KVM unit test and log the output.
        Fails the test if 'FAIL' is found in the output.
        Logs a warning if 'skip' is found.
        """
        cmd = f'./run_tests.sh {self.test_to_run}'
        self.log.debug(f"Running test command: '{cmd}'")
        status = self._run_command(cmd)
        output = status.stdout_text
        self.log.debug(f"Test command output: '{output.strip()}'")

        log_file = os.path.join("logs", f"{self.test_to_run}.log")
        self.log.debug(f"Checking for log file: {log_file}")
        if os.path.exists(log_file):
            log_content = self._run_command(f"cat {log_file}").stdout_text
            self.log.info(log_content)
            shutil.copy(log_file, os.path.join(self.logdir, f"{self.test_to_run}.log"))
            self.log.info(self._run_command(f"ls {self.logdir}").stdout_text)
        else:
            self.log.warning(f"Log file {log_file} not found.")

        if 'FAIL' in output:
            self.fail('Test Failed')
        elif 'skip' in output:
            self.log.warning(f"Test Skipped: {' '.join(output.split()[2:])}")

    def tearDown(self):
        """
        Clean up the test environment:
        - Restore the original kvm_amd/avic value.
        - Remove temporary dmesg files.
        """
        if hasattr(self, 'original_avic_value') and self.original_avic_value is not None:
            self.log.debug(f"Restoring original avic value: {self.original_avic_value} to {self.avic_path}")
            with open(self.avic_path, "w") as f:
                f.write(self.original_avic_value)
        else:
            self.log.debug("original_avic_value is None or not set, skipping restoration.")

        self.log.debug(f"Removing temporary dmesg files: dmesg_final.txt, dmesg_initial.txt")
        self._run_command("rm dmesg_final.txt dmesg_initial.txt", sudo=True, ignore_status=True)