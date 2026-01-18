import timeit
import platform
import sys
import os
import psutil
from datetime import datetime
from redvypr.redvypr_address import RedvyprAddress
import redvypr  # Um die Version zu lesen

# --- Testdaten ---
test_addr_str = "data['temp'][0] @ (i:test and p:mainhub) or data2==10"
test_pkt = {
    "_redvypr": {"packetid": "test", "publisher": "mainhub"},
    "data": {"temp": [23.5, 24.0]},
    "data2": 5
}

addr_obj = RedvyprAddress(test_addr_str)


def get_cpu_info():
    """Versucht den CPU-Namen herauszufinden."""
    if platform.system() == "Windows":
        return platform.processor()
    elif platform.system() == "Darwin":
        # macOS
        os.environ['PATH'] = os.environ['PATH'] + os.pathsep + '/usr/sbin'
        command = "sysctl -n machdep.cpu.brand_string"
        return os.popen(command).read().strip()
    elif platform.system() == "Linux":
        command = "cat /proc/cpuinfo | grep 'model name' | uniq"
        res = os.popen(command).read().split(":")
        return res[1].strip() if len(res) > 1 else platform.processor()
    return "Unknown"


def print_system_info():
    print("=" * 70)
    print(f"{'SYSTEM INFORMATION':^70}")
    print("=" * 70)
    print(f"{'Date:':<20} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'Python Version:':<20} {sys.version.split()[0]}")
    # Versucht die Redvypr Version zu finden (aus __init__ oder metadata)
    rv_version = getattr(redvypr, '__version__', 'unknown')
    print(f"{'Redvypr Version:':<20} {rv_version}")
    print("-" * 70)
    print(f"{'OS:':<20} {platform.system()} {platform.release()}")
    print(f"{'CPU:':<20} {get_cpu_info()}")
    print(
        f"{'Cores:':<20} {psutil.cpu_count(logical=False)} physical, {psutil.cpu_count(logical=True)} logical")
    print(f"{'RAM:':<20} {round(psutil.virtual_memory().total / (1024 ** 3), 2)} GB")
    print("=" * 70)
    print()


def benchmark():
    print_system_info()

    setup_parse = "from redvypr.redvypr_address import RedvyprAddress"
    stmt_parse = f"""RedvyprAddress({repr(test_addr_str)})"""

    print(f"{'Operation':<30} | {'Iter/sec':<15} | {'Time per Op':<15}")
    print("-" * 70)

    # 1. Parsing
    n_parse = 10_000
    try:
        t_parse = timeit.timeit(stmt_parse, setup=setup_parse, number=n_parse)
        print(
            f"{'Parsing (New Object)':<30} | {int(n_parse / t_parse):>15,d} | {t_parse / n_parse * 1e6:>8.2f} µs")
    except Exception as e:
        print(f"Parsing test failed: {e}")

    # 2. Execution
    n_exec = 100_000
    t_exec = timeit.timeit(lambda: addr_obj(test_pkt), number=n_exec)
    print(
        f"{'Execution (__call__)':<30} | {int(n_exec / t_exec):>15,d} | {t_exec / n_exec * 1e6:>8.2f} µs")

    # 3. Matching
    t_match = timeit.timeit(lambda: addr_obj.matches_filter(test_pkt), number=n_exec)
    print(
        f"{'Matching (Filter only)':<30} | {int(n_exec / t_match):>15,d} | {t_match / n_exec * 1e6:>8.2f} µs")
    print("-" * 70)


if __name__ == "__main__":
    benchmark()
