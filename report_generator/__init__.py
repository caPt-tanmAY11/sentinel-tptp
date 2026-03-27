# report_generator/__init__.py
# Sentinel V2 — Gen AI Compliance Report Generator
# Barclays India — Pre-Delinquency Intervention System

from .report_generator import SentinelReportGenerator
from .pdf_builder import BankReportPDFBuilder, CustomerNoticePDFBuilder

__all__ = [
    "SentinelReportGenerator",
    "BankReportPDFBuilder",
    "CustomerNoticePDFBuilder",
]
__version__ = "1.0.0"