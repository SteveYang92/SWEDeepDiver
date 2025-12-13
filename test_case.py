issue_android_app_crash = r"""
Android App使用过程发生crash，请分析原因
问题目录：examples/Android/app_crash
"""

issue_android_app_anr = r"""
Android App使用过程发生anr，请分析原因
问题目录：examples/Android/app_anr
"""

issue_android_app_oom = r"""
Android App使用过程发生oom，请分析原因
问题目录：examples/Android/app_oom
"""

issue_ios_app_crash = r"""
App使用过程发生crash，请分析原因
问题目录：examples/iOS/app_crash
"""

issue_ios_app_anr = r"""
App使用过程卡死，请分析原因
问题目录：examples/iOS/app_anr
"""

issue_ios_app_oom = r"""
App使用过程内存移出，请分析原因
问题目录：examples/iOS/app_oom
"""


issue_backend_java_oom = r"""
java oom，请分析原因
问题目录：examples/backend/java_oom
"""

issue_backend_node_crash = r"""
node 挂了，请分析原因
问题目录：examples/backend/node_crash
"""

# 测试入口
test_case_entry = issue_android_app_anr
