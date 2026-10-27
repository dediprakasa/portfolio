# wrapper so verify_module.py can verify the 10 base drills in scenarios.py
import scenarios
SCENARIOS_BASE = scenarios.SCENARIOS[:10]
assert [s["id"] for s in SCENARIOS_BASE] == ["image-pull","svc-selector","configmap-key","liveness-port","pvc-pending","init-blocked","netpol-block","ingress-path","cronjob-fail","statefulset-headless"], [s["id"] for s in SCENARIOS_BASE]
