class SieveVerifier:
    def __init__(self, mm_code):
        self.mm_code = mm_code
        self.errors = []
        self.check_array_initialization()
        self.check_loop_conditions()
        self.check_prime_collection()
    
    def check_array_initialization(self):
        # Проверка инициализации массива
        if not self.check_array_size():
            self.errors.append("Некорректный размер массива")
    
    def check_loop_conditions(self):
        # Проверка условий циклов
        if not self.check_outer_loop():
            self.errors.append("Некорректное условие внешнего цикла")
        if not self.check_inner_loop():
            self.errors.append("Некорректное условие внутреннего цикла")
    
    def check_prime_collection(self):
        # Проверка корректности сбора простых чисел
        if not self.check_prime_list():
            self.errors.append("Ошибка в сборе простых чисел")
    
    def report(self):
        if self.errors:
            return f"Верификация не пройдена:\n" + "\n".join(self.errors)
        return "Верификация прошла успешно"
