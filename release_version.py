"""将发行标签转换为 Inno Setup 所需的数字版本。"""
import re
import sys


def version_from_tag(tag):
    match = re.fullmatch(r'v(\d+\.\d+\.\d+)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?', tag)
    if not match:
        raise ValueError('版本标签应为 v1.2.3 或 v1.2.3-rc.1 格式。')
    return match.group(1)


if __name__ == '__main__':
    try:
        print(version_from_tag(sys.argv[1]))
    except (IndexError, ValueError) as exc:
        print(str(exc) or '缺少版本标签。', file=sys.stderr)
        sys.exit(1)
