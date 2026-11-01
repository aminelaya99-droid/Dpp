"""يفشل إن احتوى تقرير JUnit على إخفاقات أو أخطاء أو لم يُشغَّل أي اختبار."""
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
suites = [root] if root.tag == "testsuite" else list(root)
tests = sum(int(s.get("tests", 0)) for s in suites)
bad = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
print(f"tests={tests} failures+errors={bad}")
sys.exit(1 if bad or tests == 0 else 0)
