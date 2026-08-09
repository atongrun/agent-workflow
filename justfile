# Agent Workflow node lifecycle convenience menu.
#
# Native service definitions are profile-derived by `awf node`; this menu no
# longer renders a parallel environment-variable lifecycle.

profile := env_var_or_default("AWF_PROFILE", "")

default: doctor

_need-profile:
    @test -n "{{profile}}" || (echo "ERROR: set profile=/absolute/node-profile.json" && exit 1)

doctor: _need-profile
    awf node doctor --profile "{{profile}}"

install-service: _need-profile
    awf node install --profile "{{profile}}"

uninstall-service: _need-profile
    awf node uninstall --profile "{{profile}}"

up: _need-profile
    awf node start --profile "{{profile}}"

down: _need-profile
    awf node stop --profile "{{profile}}"

restart: _need-profile
    awf node restart --profile "{{profile}}"

status: _need-profile
    awf node status --profile "{{profile}}"

logs: _need-profile
    awf node logs --profile "{{profile}}" --lines 50
