# Загрузка правил из файла
with open('verification_rules.json') as f:
    rules = json.load(f)

verifier = MetaVerifier(rules)
ast = parse_pr_code(source_code)
errors = verifier.verify(ast)

if errors:
    print("Найденные ошибки:")
    for error in errors:
        print(f"- {error
