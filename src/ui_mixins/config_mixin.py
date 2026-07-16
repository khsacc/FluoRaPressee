import json

class ConfigMixin:
    def get_roi_for_grating(self, grating_str):
        for g in self.config.get("grating", []):
            if str(g.get("grooves")) == str(grating_str):
                r = g.get("defaultROI", {})
                return r.get("from", 100), r.get("to", 140)
        return 100, 140

    def save_config_to_file(self):
        try:
            with open("spectrometerConfig.json", "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def _load_local_cache(self):
        try:
            with open("local_cache.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_local_cache(self, key, value):
        try:
            try:
                with open("local_cache.json", "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
            data[key] = value
            with open("local_cache.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Failed to save local cache: {e}")

    def load_api_key_file(self):
        try:
            with open("fluora_pressee_api_key.json", "r", encoding="utf-8") as f:
                return json.load(f).get("api_key")
        except Exception:
            return None

    def save_api_key_file(self, key):
        try:
            with open("fluora_pressee_api_key.json", "w", encoding="utf-8") as f:
                json.dump({"api_key": key}, f, indent=4)
        except Exception as e:
            print(f"Failed to save API key: {e}")

    def load_spectrometer_config(self):
        config_path = "spectrometerConfig.json"
        default_config = {
            "model": "Andor",
            "com_port": "COM3",
            "grating": [
                {
                    "index": 1,
                    "grooves": 600,
                    "defaultROI": {"from": 100, "to": 140}
                },
                {
                    "index": 2,
                    "grooves": 1200,
                    "defaultROI": {"from": 100, "to": 140}
                },
                {
                    "index": 3,
                    "grooves": 1800,
                    "defaultROI": {"from": 100, "to": 140}
                }
            ],
            "flip_x": False,
            "default_temperature": -65
        }
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                print("spectrometerConfig.json read:", json.dumps(data, indent=2))

                if "grating" in data and len(data["grating"]) > 0 and isinstance(data["grating"][0], (int, float)):
                    new_grating = []
                    for i, g in enumerate(data["grating"]):
                        new_grating.append({
                            "index": i + 1,
                            "grooves": int(g),
                            "defaultROI": data.get("defaultROI", {"from": 100, "to": 140})
                        })
                    data["grating"] = new_grating

                    try:
                        with open(config_path, "w", encoding="utf-8") as fw:
                            json.dump(data, fw, indent=4)
                    except:
                        pass

                for key, val in default_config.items():
                    if key not in data:
                        data[key] = val
                return data
        except:
            return default_config
