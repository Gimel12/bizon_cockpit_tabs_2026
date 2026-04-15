from pynvml import *
import json
import argparse

def fix_name(s):
    # print("THe chararcter : ", s[2])
    if len(s) > 1 and s[1] == "'":
        # print("Fixing the name: ", s)
        return s[2:-1]
    return s

def get_fan(handle):
    try:
        fan = nvmlDeviceGetFanSpeed(handle)
    except:
        fan = 0
    return fan

def get_gpu_info():
    try:
        nvmlInit()
        deviceCount = nvmlDeviceGetCount()
        gpus = []
        for i in range(deviceCount):
            handle = nvmlDeviceGetHandleByIndex(i)
            info = nvmlDeviceGetMemoryInfo(handle)
            fan_pct = get_fan(handle)

            gpus.append({
                'id': i,
                'name': fix_name(str(nvmlDeviceGetName(handle))),
                'temperature': nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU),
                'gpu_utilization': nvmlDeviceGetUtilizationRates(handle).gpu,
                'memory_utilization': nvmlDeviceGetUtilizationRates(handle).memory,
                'power_usage': nvmlDeviceGetPowerUsage(handle) // 1000,
                'memory_total': info.total // 1024 // 1024,
                'fan': get_fan(handle),
                'memory_used': info.used // 1024 // 1024,
                'memory_free': info.free // 1024 // 1024,
                'memory_pct': round((info.used / info.total)*100,2)
            })
        nvmlShutdown()
        return gpus
    except NVMLError as error:
        print(f"Error fetching GPU info: {error}")
        return []


if __name__ == "__main__":
    l = list(get_gpu_info())
    d = json.dumps(l)
    print(d)
    exit(0)