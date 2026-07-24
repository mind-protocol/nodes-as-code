$ErrorActionPreference = "Stop"
python -m mind_node_runtime bootstrap --graph mind_kernel_v0
python -m mind_node_runtime emit --graph mind_kernel_v0
python -m mind_node_runtime daemon --graph mind_kernel_v0 --repo "." --once
python -m mind_node_runtime inspect --graph mind_kernel_v0
