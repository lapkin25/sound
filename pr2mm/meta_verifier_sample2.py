# Пример использования
generator = MMCodeGenerator()
generator.load_verification_rules(VERIFICATION_RULES)

# Парсинг и верификация AST
parsed_ast = parse_pr_code(source_code)
generator.verify_ast(parsed_ast)

# Генерация кода
generator.generate_function(...)
generator.generate_main(...)
