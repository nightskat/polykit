import sys
from pathlib import Path
sys.path.insert(0, str(Path('/Users/nightskat/Developer/polykit/bin')))
import lib.vendor_config as vendor_config
from lib.dispatcher import run_vendor
from lib.states import VendorProbe

def mock_load(*args, **kwargs):
    return {
        "schema_version": 3,
        "vendors": {
            "fakevendor_no_flag": {
                "binary": "true",
                "headless": "true",
                "model_flag": None,
                "models": []
            },
            "fakevendor_with_flag": {
                "binary": "true",
                "headless": "true",
                "model_flag": "--model",
                "models": ["fake-4.6"]
            }
        }
    }

vendor_config.load_vendor_config = mock_load

def run_branch(vendor, status, model="fake-4.6"):
    calls = []
    def runner(*args, **kwargs):
        class Res:
            def __init__(self):
                self.stdout = "done"
                self.stderr = ""
                if status == "ok":
                    self.returncode = 0
                elif status == "error":
                    self.returncode = 1
                elif status == "quota_capped":
                    self.returncode = 146
                    self.stderr = "insufficient credit"
        return Res()

    def detector(spec):
        if status == "not_installed":
            return VendorProbe(vendor, None, False, False)
        return VendorProbe(vendor, "/bin/true", True, False)

    import shutil
    orig_which = shutil.which
    if status == "not_installed":
        shutil.which = lambda x: None
    else:
        shutil.which = lambda x: "/bin/true"
        
    res = run_vendor(vendor, "hi", model=model, runner=runner, detector=detector)
    shutil.which = orig_which
    
    print(f"[{vendor} | {status}] status={res.status} served_model={res.served_model} reason={res.reason} warnings={res.warnings}")

print("=== NO FLAG ===")
run_branch("fakevendor_no_flag", "ok")
run_branch("fakevendor_no_flag", "error")
run_branch("fakevendor_no_flag", "quota_capped")
run_branch("fakevendor_no_flag", "not_installed")

print("=== WITH FLAG ===")
run_branch("fakevendor_with_flag", "ok")
run_branch("fakevendor_with_flag", "error")
run_branch("fakevendor_with_flag", "quota_capped")
run_branch("fakevendor_with_flag", "not_installed")
