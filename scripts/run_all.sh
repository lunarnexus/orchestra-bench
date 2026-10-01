#!/bin/bash

#MODEL="lmstudio/llmfan46/qwen3.6-35b-a3b-uncensored-heretic-native-mtp-preserved"
#config/orchestra/set-enabled-role-models $MODEL

#scripts/02-run --no-orchestra --auto all --notes "Batch101 no-orchestra"
#scripts/02-run --auto all --notes "Batch401"

#MODEL="lmstudio/ornith-1.5-35b-a3b"
#config/orchestra/set-enabled-role-models $MODEL

#scripts/02-run --no-orchestra --auto all --notes "Batch102 no-orchestra"
#scripts/02-run --auto all --notes "Batch402"


#MODEL="lmstudio/llmfan46/qwen3.6-27b-uncensored-heretic-v2-native-mtp-preserved"
#config/orchestra/set-enabled-role-models $MODEL

#scripts/02-run --no-orchestra --auto all --notes "Batch103 no-orchestra"
#scripts/02-run --auto all --notes "Batch403"

#MODEL="lmstudio/qwen/qwen3.8-27b"
#config/orchestra/set-enabled-role-models $MODEL

#scripts/02-run --no-orchestra --auto all --notes "Batch104 no-orchestra"
#scripts/02-run --auto all --notes "Batch404"


scripts/02-run --no-orchestra --auto all --notes "pass_parent_context no-orchestra baseline"
sed -i -E 's/pass_parent_context:[[:space:]]*true/pass_parent_context: false/g' config/orchestra/agent-catalog.yaml
scripts/02-run --auto all --notes "pass_parent_context:false"
sed -i -E 's/pass_parent_context:[[:space:]]*false/pass_parent_context: true/g' config/orchestra/agent-catalog.yaml
scripts/02-run --auto all --notes "pass_parent_context:true"




