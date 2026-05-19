lines = open('routes/email.py', 'rb').read().split(b'\n')
for i in range(150, 165):
    line = lines[i]
    indent = len(line) - len(line.lstrip())
    print(f'{i+1}: {indent} spaces: {repr(line[:80])}')
