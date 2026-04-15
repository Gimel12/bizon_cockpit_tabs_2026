from pynvml import *
from datetime import datetime
import json
import os
import threading

def fix_name(s):
    if len(s) > 1 and s[1] == "'":
        return s[2:-1]
    return s

def get_gpu_info():
    try:
        nvmlInit()
        deviceCount = nvmlDeviceGetCount()
        gpus = []
        for i in range(deviceCount):
            handle = nvmlDeviceGetHandleByIndex(i)
            info = nvmlDeviceGetMemoryInfo(handle)

            gpus.append({
                'id': i,
                'name': fix_name(str(nvmlDeviceGetName(handle))),
                'temperature': nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU),
                'gpu_utilization': nvmlDeviceGetUtilizationRates(handle).gpu,
                'memory_util': nvmlDeviceGetUtilizationRates(handle).memory,
                'memory_utilization': round((info.used / info.total)*100,2),
                'power_usage': nvmlDeviceGetPowerUsage(handle) // 1000,
                'memory_total': info.total // 1024 // 1024,
                'memory_used': info.used // 1024 // 1024,
                'memory_free': info.free // 1024 // 1024
            })
        nvmlShutdown()
        return gpus
    except NVMLError as error:
        print(f"Error fetching GPU info: {error}")
        return []
    


class RecordManager():
    def __init__(self, file_path, params=None):
        self.file_path = file_path
        self.stop_order = False
        if params is not None:
            self.params = params
        else:
            self.params = {   # in seconds
                "total_time": 48*60*60,
                "sample_time": 5*60,
            }
    
    
    def read_file(self):
        # if it doesn't exist, create the file
        if not os.path.exists(self.file_path):
            os.popen(f"touch {self.file_path}")
            return []
        with open(self.file_path,"r") as f:
            l = f.readlines()
        return l

    def write_file(self, lines):
        with open(self.file_path,"w") as f:
            f.writelines(lines)

    def update_record(self):
        print("Updating the record")
        lines = self.read_file()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S") 
        gpu_info = get_gpu_info()
        print(gpu_info)
        # new_rec = timestamp + " | " + json.dumps(gpu_info) + "\n"
        new_entry = {
            "timestamp": timestamp,
            "data": gpu_info
        }
        new_rec = json.dumps(new_entry) + "\n"
        max_count = self.params["total_time"] // self.params["sample_time"]
        if len(lines) >= max_count:
            lines = lines[1:] + [new_rec]
        else:
            lines.append(new_rec)
        self.write_file(lines)
    
    def stop(self):
        self.stop_order = True
    
    def record(self):
        if self.stop_order:
            return
        self.update_record()
        self.th = threading.Timer(self.params["sample_time"],self.record) 
        self.th.start()
    

if __name__ == "__main__":
    file_path ="/usr/local/share/dlbt_os/gen/nvidia-log.txt"
    # params = {   # in seconds
    #         "total_time": 48*60, # 48h = 48*60*60
    #         "sample_time": 5,    # 5min = 5*60
    # }
    rm = RecordManager(file_path)
    rm.record()