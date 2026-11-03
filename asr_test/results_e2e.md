model: models/laya-commands
device: mps
01 OK
02 OK
03 OK
04 NG
  ASR: 레드 왼쪽으로 삼 미터 가죠
  predicted: ["Select(\"red\")", "Move(\"Left\", 3)"]
  gold: ["Select(\"red\")", "Move(\"Left\", 4)"]
05 OK
06 OK
07 OK
08 OK
09 OK
10 OK
11 OK
12 OK
13 OK
14 OK
15 OK
16 NG
  ASR: 빨강이 는 앞으로 한 강 하고 오른쪽 으로 90 도 돌아
  predicted: ["Select(\"red\")", "Move(\"Front\", -1)", "Rotate(\"Right\", 90)"]
  gold: ["Select(\"red\")", "Move(\"Front\", 1)", "Rotate(\"Right\", 90)"]
17 OK
18 NG
  ASR: 초록이 앞으로 독한 빨강이 뒤 로 한칸
  predicted: ["Select(\"green\")", "Move(\"Front\", -1)", "Select(\"red\")", "Move(\"Back\", 1)"]
  gold: ["Select(\"green\")", "Move(\"Front\", 2)", "Select(\"red\")", "Move(\"Back\", 1)"]
19 NG
  ASR: 레드는 위로 색칸 가고 그리은 아래로 두칸가
  predicted: ["Select(\"red\")", "Move(\"Front\", -1)", "Select(\"green\")", "Move(\"Back\", 2)"]
  gold: ["Select(\"red\")", "Move(\"Front\", 3)", "Select(\"green\")", "Move(\"Back\", 2)"]
20 OK
21 OK
22 OK
23 OK
24 OK
25 OK
26 OK
27 NG
  ASR: 빨강이는 오른쪽으로 3미터 가고 블루는 왼쪽으로 30도 돌아 그리고 앞으로 2미터 이동해 오른쪽으로 20도 돌아쪼록기는는 오른쪽으로 아니다 돌지 말고 위로 두칸만이 이동해 그리고 빨강이는 아래로 한 칸
  predicted: ["Select(\"red\")", "Move(\"Right\", 3)", "Select(\"blue\")", "Rotate(\"Left\", 30)", "Move(\"Front\", 2)", "Rotate(\"Right\", 20)", "Select(\"green\")", "Move(\"Right\", 2)", "Select(\"red\")", "Move(\"Back\", 1)"]
  gold: ["Select(\"red\")", "Move(\"Right\", 3)", "Select(\"blue\")", "Rotate(\"Left\", 30)", "Move(\"Front\", 2)", "Rotate(\"Right\", 20)", "Select(\"green\")", "Move(\"Front\", 2)", "Select(\"red\")", "Move(\"Back\", 1)"]
28 OK
29 OK
30 OK
31 OK
32 OK
33 OK
exact: 28/33 (84.85%)
asr ms: mean 64.54, max 111.16
decide ms: mean 177.25, max 738.64
total ms: mean 241.93, max 850.14
