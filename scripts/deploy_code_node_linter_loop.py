# Graph-native ChangeSet: Code Node Linter + Fail Loud sub-loop.
from falkordb import FalkorDB
from datetime import datetime, timezone
import json, sys

GRAPH="mind_kernel_v0"
TS=datetime.now(timezone.utc).isoformat()
CS="changeset:l2:code-node-linter-v0"
LINTER="space:l2:code-node-linter-v0".REPLACE