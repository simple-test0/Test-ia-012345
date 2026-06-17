from services.agent.tools.calculator import calculator


def test_basic_arithmetic():
    assert calculator("2 ** 10 + sqrt(144)") == "1036.0"


def test_functions_and_constants():
    assert calculator("max(1, 2, 3)") == "3"
    assert calculator("round(pi, 2)") == "3.14"


def test_blocks_arbitrary_calls():
    out = calculator("__import__('os').system('ls')")
    assert "error" in out.lower()


def test_blocks_unknown_names():
    assert "error" in calculator("open('x')").lower()


def test_guards_against_huge_exponent():
    assert "error" in calculator("9 ** 99999").lower()
