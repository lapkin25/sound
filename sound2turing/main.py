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
        print(f"\nTest case {i+1}:")
        tm = TuringMachine(tm_config)
        tm.set_input(input_data)

        # Выводим начальное состояние
        print("\nНачальное состояние:")
        tm.print_tape()
        tm.print_commands()

        tm.run()

        # Выводим лог выполнения
        tm.print_log()

        # Выводим конечное состояние
        print("\nКонечное состояние:")
        tm.print_tape()

        result = tm.get_output()
        print(f"Input: {input_data}, Expected: {expected}, Got: {result}")
        assert result == expected, f"Test failed for input {input_data}"
        print("Test passed!\n")



if __name__ == "__main__":
    # Компиляция программы
    sound_program = load_sound_program('add_test.sound.json')
    compiler = SoundToTuringCompiler(sound_program)
    tm_config = compiler.compile()

    test_add()
