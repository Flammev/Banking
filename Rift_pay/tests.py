from django.test import SimpleTestCase

from .validators import (
    is_valid_name,
    is_valid_email,
    is_valid_phone,
    is_valid_password,
    is_valid_account_number,
    is_valid_otp,
    is_safe_text,
)


class ValidatorNameTests(SimpleTestCase):
    def test_simple_name_accepted(self):
        self.assertTrue(is_valid_name("Alice"))

    def test_compound_name_accepted(self):
        self.assertTrue(is_valid_name("Jean-Pierre"))

    def test_name_with_apostrophe_accepted(self):
        self.assertTrue(is_valid_name("O'Brien"))

    def test_accented_name_accepted(self):
        self.assertTrue(is_valid_name("Élodie"))

    def test_empty_name_rejected(self):
        self.assertFalse(is_valid_name(""))

    def test_none_rejected(self):
        self.assertFalse(is_valid_name(None))

    def test_name_with_digits_rejected(self):
        self.assertFalse(is_valid_name("Alice123"))

    def test_name_with_script_rejected(self):
        self.assertFalse(is_valid_name("<script>alert(1)</script>"))

    def test_name_too_long_rejected(self):
        self.assertFalse(is_valid_name("A" * 101))


class ValidatorEmailTests(SimpleTestCase):
    def test_valid_email_accepted(self):
        self.assertTrue(is_valid_email("user@example.com"))

    def test_valid_email_with_plus_accepted(self):
        self.assertTrue(is_valid_email("user+tag@example.org"))

    def test_empty_email_rejected(self):
        self.assertFalse(is_valid_email(""))

    def test_missing_at_sign_rejected(self):
        self.assertFalse(is_valid_email("userexample.com"))

    def test_missing_domain_rejected(self):
        self.assertFalse(is_valid_email("user@"))

    def test_script_as_email_rejected(self):
        self.assertFalse(is_valid_email("<script>alert(1)</script>"))

    def test_too_long_email_rejected(self):
        self.assertFalse(is_valid_email("a" * 250 + "@x.com"))


class ValidatorPhoneTests(SimpleTestCase):
    def test_international_phone_accepted(self):
        self.assertTrue(is_valid_phone("+237 612345678"))

    def test_local_phone_accepted(self):
        self.assertTrue(is_valid_phone("12345678"))

    def test_phone_with_hyphens_accepted(self):
        self.assertTrue(is_valid_phone("123-456-7890"))

    def test_empty_phone_rejected(self):
        self.assertFalse(is_valid_phone(""))

    def test_too_short_phone_rejected(self):
        self.assertFalse(is_valid_phone("1234"))

    def test_script_as_phone_rejected(self):
        self.assertFalse(is_valid_phone("<script>"))


class ValidatorPasswordTests(SimpleTestCase):
    def test_valid_password_accepted(self):
        self.assertTrue(is_valid_password("Secure1!"))

    def test_password_with_letter_and_digit_accepted(self):
        self.assertTrue(is_valid_password("abcde123"))

    def test_empty_password_rejected(self):
        self.assertFalse(is_valid_password(""))

    def test_too_short_password_rejected(self):
        self.assertFalse(is_valid_password("Ab1"))

    def test_too_long_password_rejected(self):
        self.assertFalse(is_valid_password("A1" + "x" * 127))

    def test_no_digit_password_rejected(self):
        self.assertFalse(is_valid_password("NoDigitHere"))

    def test_no_letter_password_rejected(self):
        self.assertFalse(is_valid_password("12345678"))


class ValidatorAccountNumberTests(SimpleTestCase):
    def test_valid_account_number_accepted(self):
        self.assertTrue(is_valid_account_number("ACC1234567890"))

    def test_empty_rejected(self):
        self.assertFalse(is_valid_account_number(""))

    def test_wrong_prefix_rejected(self):
        self.assertFalse(is_valid_account_number("XYZ1234567890"))

    def test_too_few_digits_rejected(self):
        self.assertFalse(is_valid_account_number("ACC123456789"))

    def test_letters_in_digits_rejected(self):
        self.assertFalse(is_valid_account_number("ACC123456789A"))


class ValidatorOtpTests(SimpleTestCase):
    def test_valid_otp_accepted(self):
        self.assertTrue(is_valid_otp("123456"))

    def test_empty_rejected(self):
        self.assertFalse(is_valid_otp(""))

    def test_too_short_rejected(self):
        self.assertFalse(is_valid_otp("12345"))

    def test_too_long_rejected(self):
        self.assertFalse(is_valid_otp("1234567"))

    def test_letters_rejected(self):
        self.assertFalse(is_valid_otp("12345a"))


class ValidatorSafeTextTests(SimpleTestCase):
    def test_normal_text_accepted(self):
        self.assertTrue(is_safe_text("Payment for services rendered"))

    def test_empty_text_accepted(self):
        self.assertTrue(is_safe_text(""))

    def test_none_accepted(self):
        self.assertTrue(is_safe_text(None))

    def test_script_tag_rejected(self):
        self.assertFalse(is_safe_text("<script>alert('xss')</script>"))

    def test_javascript_protocol_rejected(self):
        self.assertFalse(is_safe_text("javascript:void(0)"))

    def test_event_handler_rejected(self):
        self.assertFalse(is_safe_text("onclick=alert(1)"))

    def test_iframe_rejected(self):
        self.assertFalse(is_safe_text("<iframe src='evil.com'></iframe>"))

    def test_sql_select_from_rejected(self):
        self.assertFalse(is_safe_text("SELECT * FROM users"))

    def test_sql_drop_table_rejected(self):
        self.assertFalse(is_safe_text("; DROP TABLE users"))

    def test_text_with_sql_keywords_but_no_injection_accepted(self):
        # Single SQL word without the full injection pattern should pass
        self.assertTrue(is_safe_text("I want to select a product"))
