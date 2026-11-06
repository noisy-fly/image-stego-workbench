"""源码版本；打包构建时使用标签生成的版本覆盖。"""
try:
    from build_version import APP_VERSION
except ImportError:
    APP_VERSION = '0.16.0'
