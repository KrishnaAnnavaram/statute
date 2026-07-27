import sys
sys.path.insert(0, "grammar")
from antlr4 import FileStream, CommonTokenStream
from PlSqlLexer import PlSqlLexer
from PlSqlParser import PlSqlParser

path = sys.argv[1]
input_stream = FileStream(path, encoding="utf-8")
lexer = PlSqlLexer(input_stream)
stream = CommonTokenStream(lexer)
parser = PlSqlParser(stream)
tree = parser.sql_script()

def find_all(node, type_name, out):
    if type(node).__name__ == type_name:
        out.append(node)
    for i in range(getattr(node, "getChildCount", lambda: 0)()):
        find_all(node.getChild(i), type_name, out)
    return out

tables = find_all(tree, "Create_tableContext", [])
print(f"Found {len(tables)} tables")

def dump(node, depth=0, max_depth=6):
    if depth > max_depth: return
    cls = type(node).__name__
    n = getattr(node, "getChildCount", lambda: 0)()
    text = node.getText()[:40] if n == 0 else ""
    print("  "*depth + f"{cls} n={n} {text}")
    for i in range(n):
        dump(node.getChild(i), depth+1, max_depth)

# dump the accounts table (has PK, FK, CHECK)
for t in tables:
    if "accounts" in t.getText().lower()[:40]:
        dump(t, max_depth=4)
        break
