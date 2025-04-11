# KVM Unit Tests

The KVM unit tests are designed to provide functional testing for the Kernel-based Virtual Machine (KVM) by targeting specific features through minimal implementations.

This is an avocado wrapper to run KVM unit tests. It leverages the Avocado testing framework to provide a structured environment for executing KVM unit tests.

## Parameters
### Inputs
test: List of KVM unit tests to run. Default: x2apic<br>
mode: Specifies whether to run in accelerated or non-accelerated mode. Default: None<br>
kvm_module: Specifies the KVM kernel module to use (e.g., kvm_amd for AMD or kvm_intel for Intel). Default: kvm_amd<br>
target_arch (or arch): Target architecture for building the KVM unit tests. Default: x86_64<br>
cross_prefix: Prefix for cross-compiling KVM unit tests, useful when targeting a different architecture than the host<br>
qemu_binary: Path to a custom QEMU binary to use for running the tests

### Sample YAML to pass test's parameters
Define the test's parameters in the YAML:

cat ../kvm_unittest.py.data/kvm_unittest.yaml
```yaml
test: !mux
  memory:
    test: memory
  x2apic_non_accelerated:
    test: x2apic
    mode: non-accelerated
  x2apic_accelerated:
    test: x2apic
    mode: accelerated
```

**Note: Running this test alters /sys/module/kvm_amd/parameters/avic. Please restore it to its original state after the test.**

# References:
[KVM Unit Tests Documentation](https://www.linux-kvm.org/page/KVM-unit-tests)<br>
