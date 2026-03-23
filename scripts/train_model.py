"""
scripts/train_model.py
Run via: python run_pipeline.py --step train
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml_models.training_pipeline import run_training_pipeline


def run_train(max_customers=None):
    return run_training_pipeline(max_customers=max_customers)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--max-customers", type=int, default=None,
                   help="Limit customers for quick testing (default: all)")
    args = p.parse_args()
    run_train(max_customers=args.max_customers)