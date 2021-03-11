import random
import string


def generate_secure_password(length=32):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def poll_options(options):
    while True:
        for index, option in enumerate(options):
            print(f"[{index+1}]: {option}")
        val = input("Selection: ")
        try:
            selected_option = options[int(val)+1]
            break
        except TypeError:
            pass
        except ValueError:
            pass
        except IndexError:
            pass
    return selected_option
