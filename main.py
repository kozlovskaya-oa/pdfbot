a =[]
b = []
count = 0
for i in range(101):
    a.append(0)
    b.append(0)
for i in range(1, 101):
    a[i] = 50 - i

print(a)
for i in range(1, 101):
    b[i] = a[i] + 49
    print(b[i])
    if b[i] < 0:
        count += 1
print(count)