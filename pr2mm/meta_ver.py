# Пример конфигурационного файла верификации
VERIFICATION_RULES = {
    "functions": {
        "sieve": {
            "params": {"n": {"type": "int", "min": 2}},
            "returns": {"type": "array", "element_type": "int"}
        },
        "phi": {
            "params": {"n": {"type": "int", "min": 1}},
            "returns": {"type": "int", "min": 0}
        }
    },
    "arrays": {
        "checks": [
            {"type": "bounds", "message": "Выход за границы массива"},
            {"type": "init", "message": "Неинициализированный массив"}
        ]
    },
    "loops": {
        "conditions": [
            {"type": "termination", "message": "Возможный бесконечный цикл"},
            {"type": "step", "message": "Некорректный шаг цикла"}
        ]
    }
}
