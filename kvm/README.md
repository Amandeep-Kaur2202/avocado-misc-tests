# KVM Unit Tests

The KVM unit tests are designed to provide functional testing for the Kernel-based Virtual Machine (KVM) by targeting specific features through minimal implementations.

This is an avocado wrapper to run KVM unit tests. It leverages the Avocado testing framework to provide a structured environment for executing KVM unit tests.

## Parameters
### Inputs
test: List of KVM unit tests to run. Default value is x2apic.<br/> 
mode: Specifies acceleration or non acceleration mode for running KVM unit tests. Default is non-accelerated.

### Sample YAML to pass test's parameters
Define the test's parameters in the YAML:

cat ../kvm_unittest.py.data/kvm_unittest.yaml
```yaml
test: !mux
  x2apic:
    test: x2apic
mode: !mux
  accelerated:
    mode: accelerated
  non-accelerated:
    mode: non-accelerated
```

**Note: Running this test alters /sys/module/kvm_amd/parameters/avic. Please revert to the original state post-test.**
