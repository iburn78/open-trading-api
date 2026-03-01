#%% 

code = "A40000000300000030303333302D35333532392D33343230302D41414F454D00E90C00005B54485D5831392D3939343831000000E90C809395505DB4DD11A23AFB4D090000000000ADC49A601F54A9400200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000A78D32F1"

code_bytes = bytes(code, "latin1")
def decode_key(code: bytes) -> str:
    chars = "BCDFGHJKMPQRTVWXY2346789"
    pid = list(code[52:52+15])
    key = ""
    for _ in range(25):
        x = 0
        for i in range(14, -1, -1):
            x = x * 256 ^ pid[i]
            pid[i] = x // 24
            x %= 24
        key = chars[x] + key
    return "-".join(key[i:i+5] for i in range(0,25,5))


product_key = decode_key(code_bytes)
print(product_key)
