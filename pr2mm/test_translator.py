# test_translator.py

def run_test(pr_file):
    # Читаем PR-файл
    with open(pr_file, 'r') as f:
        text = f.read()
    
    # Парсим программу
    fns, entry = parse_program(normalize(text))
    
    # Создаем генератор кода
    gen = MMCodeGenerator()
    
    # Генерируем функции
    for name, fn in fns.items():
        gen.generate_function(name, fn['params'], fn['body'])
    
    # Генерируем точку входа
    gen.generate_main(entry['name'], entry['args'])
    
    # Получаем результирующий код
    mm_code = gen.emit()
    
    print(f"Сгенерированный MM-код для {pr_file}:")
    print(mm_code)
    print("\n---\n")

if __name__ == "__main__":
    # Запускаем тесты
    test_files = [
        "ackermann.pr",
        "factorial.pr",
        "simple_test.pr",
        "async_test.pr"
    ]
    
    for test in test_files:
        print(f"Тестирование файла {test}")
        run_test(test)
