import time
counter = 0
while True:
    time.sleep(1)
    counter += 1

    print(f"running！ (已运行 {counter} 秒)")
    if counter >= 100:
        break