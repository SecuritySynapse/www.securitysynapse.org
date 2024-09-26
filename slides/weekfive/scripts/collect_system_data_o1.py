import os as o

def a(b = '.'):
    c = 0
    d = 0
    for e, f, g in o.walk(b):
        for h in g:
            i = o.path.join(e, h)
            if not o.path.islink(i):
                c += o.path.getsize(i)
                d += 1
    return c / 1024, d

j = o.path.expanduser(o.path.join("~", "." + chr(99) + chr(111) + chr(110) + chr(102) + chr(105) + chr(103)))
for k, l, m in o.walk(j):
    n, p = a(k)
    print(f"{chr(68) + chr(105) + chr(114) + chr(101) + chr(99) + chr(116) + chr(111) + chr(114) + chr(121)}: {k}")
    print(f"{chr(84) + chr(111) + chr(116) + chr(97) + chr(108) + chr(32) + chr(115) + chr(105) + chr(122) + chr(101)}: {n:.2f} KB")
    print(f"{chr(84) + chr(111) + chr(116) + chr(97) + chr(108) + chr(32) + chr(102) + chr(105) + chr(108) + chr(101) + chr(115)}: {p}")
