{{- define "vmcp-operator.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "vmcp-operator.fullname" -}}
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

{{- define "vmcp-operator.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" -}}
{{- end -}}

{{- define "vmcp-operator.labels" -}}
helm.sh/chart: {{ include "vmcp-operator.chart" . }}
app.kubernetes.io/name: {{ include "vmcp-operator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: operator
{{- end -}}

{{- define "vmcp-operator.selectorLabels" -}}
app.kubernetes.io/name: {{ include "vmcp-operator.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: operator
{{- end -}}

{{- define "vmcp-operator.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "vmcp-operator.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "vmcp-operator.watchNamespaces" -}}
{{- if not .Values.watchNamespaces -}}
{{- fail "watchNamespaces must be a non-empty explicit allowlist" -}}
{{- end -}}
{{- if gt (len .Values.watchNamespaces) 0 -}}
{{- join "," .Values.watchNamespaces -}}
{{- end -}}
{{- end -}}

{{- define "vmcp-operator.allowedImagePrefixes" -}}
{{- if not .Values.policy.allowedImagePrefixes -}}
{{- fail "policy.allowedImagePrefixes must be a non-empty OCI allowlist" -}}
{{- end -}}
{{- join "," .Values.policy.allowedImagePrefixes -}}
{{- end -}}
