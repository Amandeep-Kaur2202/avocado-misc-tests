# KVM Unit Tests (Avocado)

This Avocado test suite is designed to validate the functionality of Kernel-based Virtual Machine (KVM). It leverages the Avocado testing framework to provide a structured environment for executing KVM unit tests.

1. Executes Tests: Runs the specified KVM unit test with configurable parameters.
2. Supported Tests: This test suite is designed to run individual tests available within the KVM unit tests repository.

## Parameters

The test execution can be customized using the following Avocado parameters:

`test` (default: `x2apic`)**: Specifies the name of the KVM unit test to run. This parameter corresponds to the test executable within the built test suite (e.g., `x2apic`).

## Example Usage (Avocado)

```bash
# To run a specific test (e.g., `x2apic`) in accelerated mode:
avocado run ../kvm_unittest.py -p test="x2apic" --max-parallel-tasks=1

# To run a specific test (e.g., `x2apic`) with a YAML configuration:
avocado run ../kvm_unittest.py -m ../kvm_unittest.py.data/kvm_unittest.yaml --max-parallel-tasks=1
