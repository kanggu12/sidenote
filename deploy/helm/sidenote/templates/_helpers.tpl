{{/*
Names and labels. Every object is called "<fullname>-<component>", where the components are server,
runner, llm, llm-pull and searxng: with a release called "sidenote", the server's Service is
"sidenote-server".
*/}}

{{- define "sidenote.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "sidenote.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* "<fullname>-<component>". Call with (dict "context" $ "component" "server"). */}}
{{- define "sidenote.componentName" -}}
{{- printf "%s-%s" (include "sidenote.fullname" .context) .component | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* The labels a component's pods are selected by. Call with (dict "context" $ "component" "server"). */}}
{{- define "sidenote.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sidenote.name" .context }}
app.kubernetes.io/instance: {{ .context.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* Every label of a component's objects. Same argument as sidenote.selectorLabels. */}}
{{- define "sidenote.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .context.Chart.Name .context.Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "sidenote.selectorLabels" . }}
app.kubernetes.io/version: {{ .context.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .context.Release.Service }}
{{- end -}}

{{/* "repository:tag", the tag defaulting to the chart's appVersion. Call with (dict "context" $ "image" .Values.server.image). */}}
{{- define "sidenote.image" -}}
{{- printf "%s:%s" .image.repository (toString (.image.tag | default .context.Chart.AppVersion)) -}}
{{- end -}}

{{/* storageClassName for a persistence block: left out when empty (the default class), "" for "-". */}}
{{- define "sidenote.storageClass" -}}
{{- if .storageClass -}}
{{- if eq "-" (toString .storageClass) -}}
storageClassName: ""
{{- else -}}
storageClassName: {{ .storageClass | quote }}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* A map as container environment variables, each value as a string. Null values are left out. */}}
{{- define "sidenote.envFromMap" -}}
{{- range $name, $value := . }}
{{- if not (kindIs "invalid" $value) }}
- name: {{ $name | quote }}
  value: {{ $value | toString | quote }}
{{- end }}
{{- end }}
{{- end -}}

{{/* The server image's HEALTHCHECK (docker/Dockerfile), as an exec probe command. */}}
{{- define "sidenote.server.healthCommand" -}}
- python
- -c
- "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8777/health', timeout=4)"
{{- end -}}

{{/* The claim names, for the Deployments and the model-pull Job alike. */}}
{{- define "sidenote.server.claimName" -}}
{{- .Values.server.persistence.existingClaim | default (printf "%s-data" (include "sidenote.componentName" (dict "context" . "component" "server"))) -}}
{{- end -}}

{{- define "sidenote.llm.claimName" -}}
{{- .Values.llm.persistence.existingClaim | default (printf "%s-models" (include "sidenote.componentName" (dict "context" . "component" "llm"))) -}}
{{- end -}}

{{/*
Where the agent's login files are mounted: the folder its CLI reads them from. Empty when there is
no Secret, or the provider signs in with an environment variable (anthropic-api) or not at all.
*/}}
{{- define "sidenote.agent.loginDir" -}}
{{- if .Values.agent.auth.existingSecret -}}
{{- if eq .Values.agent.provider "claude-code" -}}
/root/.claude
{{- else if eq .Values.agent.provider "codex" -}}
{{- /* Codex writes into its home as it works, so its login is copied there (server-deployment.yaml, codex-home) */ -}}
/etc/sidenote/agent-login
{{- end -}}
{{- end -}}
{{- end -}}

{{/* The Secret that holds the code runner's token (templates/runner-token-secret.yaml). */}}
{{- define "sidenote.runner.tokenSecret" -}}
{{- if .Values.runner.existingSecret -}}
{{- .Values.runner.existingSecret -}}
{{- else -}}
{{- printf "%s-token" (include "sidenote.componentName" (dict "context" . "component" "runner")) -}}
{{- end -}}
{{- end -}}

{{/* Settings that cannot work, refused before anything is rendered. */}}
{{- define "sidenote.validate" -}}
{{- $providers := list "claude-code" "codex" "anthropic-api" "off" -}}
{{- if not (has (toString .Values.agent.provider) $providers) -}}
{{- fail (printf "agent.provider must be claude-code, codex, anthropic-api or off, not %q" (toString .Values.agent.provider)) -}}
{{- end -}}
{{- $user := .Values.server.env | default dict -}}
{{- range $name := list "SIDENOTE_HOST" "SIDENOTE_PORT" "SIDENOTE_LOG_DIR" "HF_HOME" "SIDENOTE_AGENT" "SIDENOTE_AGENT_MODEL" "SIDENOTE_AGENT_EFFORT" "ANTHROPIC_API_KEY" "CLAUDE_CODE_OAUTH_TOKEN" "SIDENOTE_RUNNER_TOKEN" "SIDENOTE_TRUST_GATEWAY" -}}
{{- if hasKey $user $name -}}
{{- fail (printf "server.env.%s is not accepted: the comment above server.env in values.yaml says what sets it" $name) -}}
{{- end -}}
{{- end -}}
{{- if and (not .Values.llm.enabled) (eq (toString .Values.agent.provider) "off") (not (hasKey $user "SIDENOTE_LOCAL_URL")) (not (hasKey $user "SIDENOTE_ANALYZER")) -}}
{{- fail "llm.enabled=false with agent.provider=off leaves the server nothing to solve with: keep the local LLM, choose an agent, or name another model server in server.env.SIDENOTE_LOCAL_URL" -}}
{{- end -}}
{{- if lt (int .Values.llm.gpu) 0 -}}
{{- fail "llm.gpu cannot be negative" -}}
{{- end -}}
{{- end -}}

{{/*
The server's environment, as compose.yaml's "environment" block sets it: the chart's own values,
then server.env over them, then the values the chart fixes (refused in server.env by
sidenote.validate). Rendered as a list for "env:".
*/}}
{{- define "sidenote.server.env" -}}
{{- $user := .Values.server.env | default dict -}}
{{- $env := dict -}}
{{- $_ := set $env "TZ" .Values.timezone -}}
{{- /* compose.yaml: OMP_NUM_THREADS follows SIDENOTE_WHISPER_THREADS (4), and idle OpenMP threads do not spin. */ -}}
{{- $_ := set $env "OMP_NUM_THREADS" (toString (index $user "SIDENOTE_WHISPER_THREADS" | default "4")) -}}
{{- $_ := set $env "OMP_WAIT_POLICY" "PASSIVE" -}}
{{- /* The CLI in the image is a helper for this server: no self-update, no telemetry or error reports. */ -}}
{{- $_ := set $env "DISABLE_AUTOUPDATER" "1" -}}
{{- $_ := set $env "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" "1" -}}
{{- /* The code runner over TCP (its Service), where compose uses a Unix socket. Empty turns the run button off. */ -}}
{{- if .Values.runner.enabled -}}
{{- $_ := set $env "SIDENOTE_RUNNER_URL" (printf "http://%s:%v/run" (include "sidenote.componentName" (dict "context" . "component" "runner")) .Values.runner.port) -}}
{{- else -}}
{{- $_ := set $env "SIDENOTE_RUNNER_URL" "" -}}
{{- end -}}
{{- if .Values.llm.enabled -}}
{{- $_ := set $env "SIDENOTE_LOCAL_URL" (printf "http://%s:11434/v1" (include "sidenote.componentName" (dict "context" . "component" "llm"))) -}}
{{- else if not (or (hasKey $user "SIDENOTE_LOCAL_URL") (hasKey $user "SIDENOTE_ANALYZER")) -}}
{{- /* No local LLM and none named: the agent alone solves, and the server stops looking for a local LLM at its default address (http://llm:11434/v1), which does not resolve here. */ -}}
{{- $_ := set $env "SIDENOTE_ANALYZER" "agent" -}}
{{- end -}}
{{- /* SIDENOTE_SEARCH_URL is read as it is, so an empty value turns web search off. */ -}}
{{- if .Values.search.enabled -}}
{{- $_ := set $env "SIDENOTE_SEARCH_URL" (printf "http://%s:8080/search" (include "sidenote.componentName" (dict "context" . "component" "searxng"))) -}}
{{- else -}}
{{- $_ := set $env "SIDENOTE_SEARCH_URL" "" -}}
{{- end -}}
{{- /* server.env over the chart's values, copied key by key: sprig's merge would replace a user's "" with the chart's value. */ -}}
{{- range $name, $value := $user -}}
{{- $_ := set $env $name $value -}}
{{- end -}}
{{- /* Fixed: the Service, the probes and the mounts depend on these. */ -}}
{{- $_ := set $env "SIDENOTE_HOST" "0.0.0.0" -}}
{{- $_ := set $env "SIDENOTE_PORT" "8777" -}}
{{- $_ := set $env "SIDENOTE_LOG_DIR" "/data/logs" -}}
{{- /* Only loopback is trusted: kubectl port-forward and the probes arrive there, while the pod's gateway is the
node's bridge, which anything on the node can come from (a NetworkPolicy cannot stop the node). */ -}}
{{- $_ := set $env "SIDENOTE_TRUST_GATEWAY" "0" -}}
{{- $_ := set $env "HF_HOME" "/data/hf" -}}
{{- /* Kubernetes starts a container that ended again itself (with its back-off, and the liveness probe): the image's own loop, which does that under compose (docker/keep-running.sh), stands aside so a pod's restarts stay the cluster's to count. */ -}}
{{- $_ := set $env "SIDENOTE_SELF_RESTART" "0" -}}
{{- $_ := set $env "SIDENOTE_AGENT" (toString .Values.agent.provider) -}}
{{- with .Values.agent.model -}}
{{- $_ := set $env "SIDENOTE_AGENT_MODEL" (toString .) -}}
{{- end -}}
{{- with .Values.agent.effort -}}
{{- $_ := set $env "SIDENOTE_AGENT_EFFORT" (toString .) -}}
{{- end -}}
{{- include "sidenote.envFromMap" $env }}
{{- if .Values.runner.enabled }}
# The token the runner takes runs with: over TCP its port is open to whatever can reach it.
- name: SIDENOTE_RUNNER_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "sidenote.runner.tokenSecret" . | quote }}
      key: token
{{- end }}
{{- $secret := .Values.agent.auth.existingSecret -}}
{{- if and $secret (eq (toString .Values.agent.provider) "anthropic-api") }}
- name: ANTHROPIC_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ $secret | quote }}
      key: ANTHROPIC_API_KEY
{{- else if and $secret (eq (toString .Values.agent.provider) "claude-code") }}
# A long-lived token from `claude setup-token`, when the Secret holds one: it needs no refresh.
- name: CLAUDE_CODE_OAUTH_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ $secret | quote }}
      key: CLAUDE_CODE_OAUTH_TOKEN
      optional: true
{{- end }}
{{- end -}}

{{/* The models the pull Job downloads: llm.pull.models, or the server's two local models as `./sidenote llm pull`
takes them. "auto" (the server's default) is the largest measured model that fits the GPU and its smaller one, by
TIERS and MARGIN_GB in server/models.py. The pod cannot read the GPU, so its memory is SIDENOTE_LOCAL_VRAM_GB, and
a 24 GB GPU when that is not set. Nothing fits below 6.5 GB: the agent then solves every problem. */}}
{{- define "sidenote.llm.pullModels" -}}
{{- $models := .Values.llm.pull.models -}}
{{- if not $models -}}
{{- $user := .Values.server.env | default dict -}}
{{- $smaller := dict "sidenote-gemma4:26b" "sidenote-gemma4:e4b" "sidenote-gemma4:31b" "sidenote-gemma4:e4b" "sidenote-gemma4:e4b" "sidenote-gemma4:e2b" -}}
{{- $vram := toString (index $user "SIDENOTE_LOCAL_VRAM_GB" | default "24") | float64 -}}
{{- $main := toString (index $user "SIDENOTE_LOCAL_MODEL" | default "auto") -}}
{{- if eq $main "auto" -}}
{{- if ge $vram 22.5 }}{{ $main = "sidenote-gemma4:26b" }}{{ else if ge $vram 9.5 }}{{ $main = "sidenote-gemma4:e4b" }}{{ else if ge $vram 6.5 }}{{ $main = "sidenote-gemma4:e2b" }}{{ else }}{{ $main = "" }}{{ end -}}
{{- end -}}
{{- $busy := ternary (toString (index $user "SIDENOTE_LOCAL_BUSY_MODEL")) "auto" (hasKey $user "SIDENOTE_LOCAL_BUSY_MODEL") -}}
{{- if eq $busy "auto" -}}
{{- $busy = index $smaller $main | default (index $smaller (printf "sidenote-%s" $main)) | default "" -}}
{{- end -}}
{{- $models = list -}}
{{- range (list $main $busy) }}{{ if . }}{{ $models = append $models . }}{{ end }}{{ end -}}
{{- $models = $models | uniq -}}
{{- end -}}
{{- toJson $models -}}
{{- end -}}
