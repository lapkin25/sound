import json
from sound2turing import SoundToTuringCompiler
from turing_machine import TuringMachine

def load_sound_program(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def test_add():
    test_cases = [
        ([[1], [1]], [1, 0]),
        ([[1], [0]], [1]),
        ([[1, 0], [1]], [1, 1]),
        ([[1, 1], [1, 0]], [1, 0, 1])
    ]
    
    for i, (input_data, expected) in enumerate(test_cases):
        print(f"\nТестовый пример {i+1}:")
        tm = TuringMachine(tm_config)
        tm.set_input(input_data)
        
        print("\nНачальное состояние:")
        tm.print_tape()
        tm.print_commands()
        
        print("\nЗапуск машины Тьюринга...")
        tm.run()
        
        print("\nПодробный лог выполнения:")
        tm.print_log()
        
        print("\nКонечное состояние:")
        tm.print_tape()
        
        result = tm.get_output()
        print(f"Входные данные: {input_data}")
        print(f"Ожидаемый результат: {expected}")
        print(f"Полученный результат: {result}")
        
        assert result == expected, f"Ошибка в тестовом примере для входных данных {input_data}"
        print("Тест пройден!\n")



if __name__ == "__main__":
    # Компиляция программы
    sound_program = load_sound_program('add_test.sound.json')
    compiler = SoundToTuringCompiler(sound_program)
    tm_config = compiler.compile()

    test_add()
