import ast, re

text = open("byou/api.py", "r", encoding="utf-8").read()
ast.parse(text)
print("Syntax: OK")

routes = re.findall(r'@app\.(get|post)\("([/\w]+)"', text)
print(f"Routes: {len(routes)}")
for method, path in routes:
    print(f"  {method.upper()} {path}")
