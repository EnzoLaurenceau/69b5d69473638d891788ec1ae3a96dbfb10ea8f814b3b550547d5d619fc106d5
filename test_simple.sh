#!/bin/bash

prompt=$(cat test_triage.txt)

echo "════════════════════════════════════════════════════════════"
echo "  HAIKU TEST — Issue Triage"
echo "════════════════════════════════════════════════════════════"
echo ""

# Direct curl call
response=$(curl -s https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "content-type: application/json" \
  -d "{
    \"model\": \"claude-haiku-4-5-20251001\",
    \"max_tokens\": 1000,
    \"messages\": [{\"role\": \"user\", \"content\": $(echo "$prompt" | jq -Rs .)}]
  }")

echo "✅ Raw response:"
echo "$response" | jq '.usage' 2>/dev/null || echo "Parse failed"

# Extract metrics
input_tokens=$(echo "$response" | jq -r '.usage.input_tokens // "?"')
output_tokens=$(echo "$response" | jq -r '.usage.output_tokens // "?"')
total=$((input_tokens + output_tokens))

echo ""
echo "📊 METRICS:"
echo "  Input:  $input_tokens tokens"
echo "  Output: $output_tokens tokens"
echo "  Total:  $total tokens"

# Save
echo "$response" | jq '.usage' > test_haiku_metrics.json
