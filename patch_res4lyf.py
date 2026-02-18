"""
Patch RES4LYF to add beta57 to standard SCHEDULER_NAMES
"""
import comfy.samplers

# Add beta57 to standard scheduler names
if "beta57" not in comfy.samplers.SCHEDULER_NAMES:
    comfy.samplers.SCHEDULER_NAMES.append("beta57")
    print("[PatchRES4LYF] Added 'beta57' to SCHEDULER_NAMES")

print("[PatchRES4LYF] Patch applied successfully")
