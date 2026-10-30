path = r'C:\Users\HP\Downloads\talim_pro_project\talim_pro\templates\school\dashboard.html'
with open(path, 'rb') as f:
    data = f.read()

marker = b"{% elif user.role == 'student' %}"
idx = data.find(marker)
if idx < 0:
    print("Student marker not found")
else:
    # Find the teacher section start
    teacher_start = data.find(b"{% elif user.role == 'teacher' %}")
    if teacher_start < 0:
        print("Teacher marker not found")
    else:
        # Insert the groups block right before the student marker
        insert = b'''
<h3 style="margin:20px 0 10px 0;">Guruhlarim</h3>
<div class="group-grid">{% for group in groups %}<div class="group-card"><span class="group-icon">\xe2\x96\xa4</span><div><b>{{ group.name }}</b><small>{{ group.subject }}</small><small>{{ group.students.count }} nafar o\xe2\x80\x98quvchi</small></div><div class="group-actions"><a class="text-link" href="{% url 'add_student_to_group' group_id=group.pk %}">O\xe2\x80\x98quvchi qo\xe2\x80\x98shish \xe2\x86\x92</a></div></div>{% empty %}<p class="empty">Hozircha guruh yo\xe2\x80\x98q. Administrator guruhga biritganda shu yerda ko\xe2\x80\x98rinadi.</p>{% endfor %}</div>
'''
        data = data[:idx] + insert + data[idx:]
        with open(path, 'wb') as f:
            f.write(data)
        print("Insertion successful")
