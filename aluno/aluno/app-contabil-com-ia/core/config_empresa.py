"""Validação de documentos brasileiros para cadastros de empresa e participantes.

Somente formato e dígitos verificadores: o app não consulta receitas externas.
"""
import re

_SO_DIGITOS = re.compile(r'\D')


def _digitos(valor):
    return _SO_DIGITOS.sub('', valor or '')


def _dv_mod11(chave, pesos):
    soma = sum(int(d) * p for d, p in zip(chave, pesos))
    resto = soma % 11
    dv = 11 - resto
    return '0' if dv >= 10 else str(dv)


def cnpj_valido(valor):
    """Confere os dois dígitos verificadores de um CNPJ de 14 dígitos."""
    d = _digitos(valor)
    if len(d) != 14 or d == d[0] * 14:
        return False
    base, dv = d[:12], d[12:]
    calc = _dv_mod11(base, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    calc += _dv_mod11(base + calc, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return dv == calc


def cpf_valido(valor):
    """Confere os dois dígitos verificadores de um CPF de 11 dígitos."""
    d = _digitos(valor)
    if len(d) != 11 or d == d[0] * 11:
        return False
    base, dv = d[:9], d[9:]
    calc = _dv_mod11(base, [10, 9, 8, 7, 6, 5, 4, 3, 2])
    calc += _dv_mod11(base + calc, [11, 10, 9, 8, 7, 6, 5, 4, 3, 2])
    return dv == calc


def formatar_cnpj(d):
    return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}'


def formatar_cpf(d):
    return f'{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}'


def normalizar_documento(valor):
    """Aceita CNPJ (14) ou CPF (11) com ou sem máscara; '' fica vazio.

    Devolve o documento formatado ou levanta ValueError com mensagem clara.
    """
    d = _digitos(valor)
    if not d:
        return ''
    if len(d) == 14:
        if not cnpj_valido(d):
            raise ValueError('CNPJ inválido: confira os dígitos informados.')
        return formatar_cnpj(d)
    if len(d) == 11:
        if not cpf_valido(d):
            raise ValueError('CPF inválido: confira os dígitos informados.')
        return formatar_cpf(d)
    raise ValueError('Documento deve ser CNPJ (14 dígitos) ou CPF (11 dígitos).')
