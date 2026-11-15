{{- define "appLabels" -}}
app: {{ .Chart.Name | quote }}
instance: {{ .Release.Name }}
team: {{ (index .Chart.Maintainers 0).Name | quote }}
{{- end }}

{{- define "appSelectorLabels" -}}
app: {{ .Chart.Name | quote }}
instance: {{ .Release.Name }}
{{- end }}
