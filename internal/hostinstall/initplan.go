package hostinstall

// InitializationPlan renders reviewable proposed files. It grants no native
// write, account, credential, execution or service capability.
type InitializationPlan struct {
	Schema         int               `json:"schema"`
	ReadyToInstall bool              `json:"readyToInstall"`
	HostConfig     map[string]any    `json:"hostConfig"`
	Units          map[string]string `json:"units"`
	Activation     []string          `json:"activation"`
	Pending        []string          `json:"pending"`
}

func BuildInitializationPlan(m Manifest) (InitializationPlan, error) {
	if err := m.Validate(); err != nil {
		return InitializationPlan{}, err
	}
	p := InitializationPlan{Schema: 1, ReadyToInstall: false,
		HostConfig: map[string]any{
			"enableMaintenance": true, "listen": "127.0.0.1:7070", "internalUrl": "http://127.0.0.1:7070",
			"dataDir": "/var/lib/awf", "piAgentDir": "/var/lib/awf/pi-agent", "piProvider": "magpie",
			"tokenEnv": "AWF_HOST_TOKEN", "extensionTokenEnv": "AWF_EXTENSION_TOKEN",
			"piBinary": "/opt/pi-cli/bin/pi", "piExtension": "/opt/awf/extensions/awf.ts",
			"projects": map[string]string{}, "nodes": map[string]string{},
		},
		Units: map[string]string{"awf-host.service": hostUnitProposal, "awf-magpie.service": magpieUnitProposal},
		Activation: []string{
			"Verify pinned component bytes, notices, full Pi dependency closure and extension module resolution",
			"Prepare fixed program roots and the awf service account; inspect existing ownership and installations",
			"Explicitly initialize independent service credentials and actual Magpie catalog; require LAN=false",
			"Verify loopback listeners and exact native build/version identity in the approved acceptance environment",
			"On upgrades: acquire durable maintenance owner/revision, drain, seal, stop both systemd units and verify process groups exited",
			"Activate compatible fixed programs atomically under a native transaction, start and verify services, explicitly release original lease",
		},
		Pending: []string{
			"Native install/activation adapter is unimplemented; fixture selectors do not authorize these actions",
			"Equivalent shared launcher and official managed releases-v1 route verified in private fixture; native launch and network upgrades remain unaccepted",
			"Runtime fixture prepares full pinned Node/npm and verified Pi closure; native program ownership and activation remain unimplemented",
			"Native programs must be administrator-owned and service-read-only; explicit administrator upgrades must retain the maintenance and systemd stop boundary",
			"AWF extension TypeBox/Pi resolution verified in offline fixture; native distribution notices and full product acceptance remain pending",
			"Magpie LAN setting overrides MAGPIE_ADDR; independent config and native socket checks must enforce loopback",
			"Unit receipt conditions below are proposed adapter outputs, never created by current code",
		},
	}
	return p, nil
}

// Fixed literal text prevents manifest values from becoming systemd directives.
// Conditions deliberately depend on future acceptance receipts, not fixture ones.
const hostUnitProposal = `[Unit]
Description=AWF Go Host (proposed, native adapter pending)
After=network-online.target awf-magpie.service
Wants=network-online.target
Requires=awf-magpie.service
ConditionPathExists=/etc/awf/native-initialized.json

[Service]
Type=simple
User=awf
Group=awf
WorkingDirectory=/var/lib/awf
Environment=HOME=/var/lib/awf
Environment=PATH=/opt/node/bin:/usr/bin:/bin
Environment=PI_CODING_AGENT_DIR=/var/lib/awf/pi-agent
EnvironmentFile=/etc/awf/host.env
ExecStart=/opt/awf/awf host --config /etc/awf/host.json
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=60
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/awf /var/cache/awf

[Install]
WantedBy=multi-user.target
`

const magpieUnitProposal = `[Unit]
Description=AWF Magpie gateway (proposed, LAN=false acceptance required)
After=network-online.target
Wants=network-online.target
ConditionPathExists=/etc/awf/native-magpie-loopback.json

[Service]
Type=simple
User=awf
Group=awf
WorkingDirectory=/var/lib/awf
Environment=HOME=/var/lib/awf
Environment=XDG_CONFIG_HOME=/var/lib/awf/magpie-config
Environment=XDG_CACHE_HOME=/var/cache/awf
Environment=MAGPIE_ADDR=127.0.0.1:3425
ExecStart=/opt/magpie/magpie serve
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=60
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/awf /var/cache/awf

[Install]
WantedBy=multi-user.target
`
