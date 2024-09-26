import os

def get_dir_size_and_file_count(start_path = '.'):
    total_size = 0
    file_count = 0
    for dirpath, dirnames, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)
                file_count += 1
    return total_size / 1024, file_count

config_dir = os.path.expanduser("~/.config")
for root, dirs, files in os.walk(config_dir):
    size, count = get_dir_size_and_file_count(root)
    print(f"Directory: {root}")
    print(f"Total size: {size:.2f} KB")
    print(f"Total files: {count}")
