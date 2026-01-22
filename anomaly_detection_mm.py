import numpy as np
from sklearn import svm
import argparse


def anomaly_detection():
    data = np.array(
        [
            10,
            12,
            12,
            13,
            12,
            11,
            14,
            13,
            15,
            10,
            10,
            11,
            15,
            13,
            14,
            12,
            14,
            15,
            10,
            300,
        ]
    )
    data = data.reshape(-1, 1)
    clf = svm.OneClassSVM(kernel="linear", nu=0.01)
    clf.fit(data)
    pred = clf.predict(data)
    print(pred)


def run(args):
    if args.print:
        print(args.print)

    if args.loop:
        for i in range(10):
            print(i)

    if args.anomaly:
        anomaly_detection()

    if args.quit:
        quit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--print", type=str, help="Text to print")
    parser.add_argument("--loop", action="store_true", help="Loop through numbers 0-9")
    parser.add_argument("--anomaly", action="store_true", help="Run anomaly detection")
    parser.add_argument("--quit", action="store_true", help="Quit program")
    args = parser.parse_args()

    print(
        "Legal Disclaimer: This software is provided 'as is', without any express or implied warranty. In no event will the authors be held liable for any damages arising from the use of this software. Always ensure that your use of AI respects privacy, fairness, and legality. Always get appropriate legal advice and make sure your program adheres to all local and international laws."
    )
    run(args)


if __name__ == "__main__":
    main()
