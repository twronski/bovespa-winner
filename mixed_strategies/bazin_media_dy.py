#!/usr/bin/env python3

# A idéia é calcular o ranking (Bazin) das ações analisando os dados fundamentalistas de todas as empresas da bolsa B3

# Para a análise, são utilizados princípios do Décio Bazin
# Ele é autor do livro: "Faça Fortuna Com Ações", que é tido como literatura indicada
# por Luis Barsi, o maior investidor na bolsa brasileira.

# Princípios utilizados:

# - [x] 1. Preço Justo (Bazin) > 1.5 * Preço. Preço Justo (Bazin) => Dividend Yield * 16.67 (Por: Décio Bazin)
# - [x] 2. Dívida Bruta/Patrimônio < 0.5 (50%)
# - [x] 3. Dividend Yield > 0.06 (6%)
# - [x] 4. Média do Dividend Yield nos últimos 5 anos > 0.05 (5%)
# - [x] 5. Pagamento constante de dividendos nos últimos 5 anos
# - [x] 6. Pagamento crescente de dividendos nos últimos 5 anos
# - [x] 7. 0 < Payout < 1

import sys, os
sys.path.extend([f'../{name}' for name in os.listdir("..") if os.path.isdir(f'../{name}')])

import fundamentus
import bovespa
import backtest
import browser

import pandas
import numpy
import urllib.parse

from math import sqrt
from decimal import Decimal

import http.cookiejar
import urllib.request
import json
import threading
import time
import subprocess

# === Parallel fetching... https://stackoverflow.com/questions/16181121/a-very-simple-multithreading-parallel-url-fetching-without-queue

# Pega o histórico dos Dividendos...
# DPA => Dividendo Por Ação. Esse que é importante!
# https://api-analitica.sunoresearch.com.br/api/Indicator/GetIndicatorsYear?ticker=PETR4
# Pega Histórico de: year, cresRec, divBruta, data, qntAcoes, cotacao, pl, pvp, pebit, pfco, psr, pAtivos, pCapGiro, pAtivCLiq, divYeld, evebit, valordaFirma, valordeMercado, fci, dbPl, vpa, margBruta, capex, margLiq, capexLL, giroAtivos, fcf, caixaLivre, fcl, payout, lpa, margEbit, roic, ebitAtivo, fco, dpa, liqCorrent, divBrPatrim, capexFco, fct, ativoCirculante, fciLL, capexDetails, roe, roa, dlpl, payoutDetails, ebit, lucroLiquido, receitaLiquida

# Pega o histórico de Dividend Yield...
# Últimos 5 anos...
# https://statusinvest.com.br/acao/companytickerprovents?ticker=TRPL4&chartProventsType=1

# Últimos 20 anos...
# https://statusinvest.com.br/acao/companytickerprovents?ticker=TRPL4&chartProventsType=2

# Futura análise da análise ()
# https://statusinvest.com.br/acao/getrevenue?companyName=enauta&type=0&trimestral=false

# Populate shares panda dataframe with the provided year
def populate_shares(year):
  globals()['year'] = year
  globals()['infos'] = {}
  
  if year == current_year():
    shares = bovespa.shares()
  else:
    shares = fundamentus.shares(year)
  
  shares = shares[shares['Cotação'] > 0]
  shares = shares[shares['Liquidez 2 meses'] > 0]
  shares['Ranking (Bazin)'] = 0
  
  fill_infos(shares)
  
  shares = add_ratings(shares)
  
  shares = reorder_columns(shares)
  
  return shares


# Captura a situação dos dividendos nos últimos 5 anos. (Captura do site: Suno Analitica)
# infos = {
#   'TRPL4': { 'constante': False, 'crescente': False },
#   'PETR4': { 'constante': False, 'crescente': False }
# }
def fill_infos(shares):
  cookie_jar = http.cookiejar.CookieJar()
  opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
  opener.addheaders = [('User-agent', 'Mozilla/5.0 (Windows; U; Windows NT 6.1; rv:2.2) Gecko/20110201'),
                       ('Accept', 'text/html, text/plain, text/css, text/sgml, */*;q=0.01')]
  tickers = list(shares.index)
  threads = [threading.Thread(target=fill_infos_by_ticker, args=(ticker,opener,)) for ticker in tickers]
  for thread in threads:
    thread.start()
  for thread in threads:
    thread.join()

def fill_infos_by_ticker(ticker, opener):
  infos[ticker] = {
    'ultimos_dy': 0.0,
    'constante': False,
    'crescente': False,
    'healthy_payout': False
  }
  
  current_year = year
  
  # Fetching LPA's and DPA's
  url = f'https://api-analitica.sunoresearch.com.br/api/Indicator/GetIndicatorsYear?ticker={ticker}'
  with opener.open(url) as link:
    company_indicators = link.read().decode('ISO-8859-1')
  company_indicators = json.loads(company_indicators)
  
  # Only consider company indicators before the current_year (robust solution for backtesting purposes)
  company_indicators = [ci for ci in company_indicators if ci['year'] < current_year]
  
  last_dpas = [fundament['dpa'] for fundament in company_indicators] # Bazin
  last_payouts = [fundament['payout'] for fundament in company_indicators] # Bazin
  last_divYields = [fundament['divYeld'] for fundament in company_indicators] # Bazin
  
  if (len(last_divYields[:5]) > 0):
    infos[ticker]['ultimos_dy'] = (sum(last_divYields[:5]) / len(last_divYields[:5]))
  
  if (len(last_dpas[:5]) > 0):
    infos[ticker]['constante'] = all(last_dpas[:5][i] > 0 for i in range(len(last_dpas[:5])))
    infos[ticker]['crescente'] = all(last_dpas[:5][i] >= last_dpas[:5][i+1] for i in range(len(last_dpas[:5])-1))
  
  if (len(last_divYields[:5]) > 0):
    infos[ticker]['healthy_payout'] = all((last_payouts[:5][i] > 0) & (last_payouts[:5][i] < 1) for i in range(len(last_payouts[:5])))

def add_ratings(shares):
  add_bazin_columns(shares)
  fill_score(shares)
  fill_score_explanation(shares)
  return fill_special_infos(shares)

def add_bazin_columns(shares):
  shares['Bazin Score'] = Decimal(0)
  shares['Preço Justo (Bazin)'] = shares['Dividend Yield'] * 100 * Decimal(16.67)
  shares['Preço Justo (Bazin) / Cotação'] = shares['Preço Justo (Bazin)'] / shares['Cotação']
  shares['Media de Dividend Yield dos Últimos 5 anos'] = Decimal(0.0)
  shares['Dividendos > 5% na média dos últimos 5 anos'] = False
  shares['Dividendos Constantes Ultimos 5 Anos'] = False
  shares['Dividendos Crescentes Ultimos 5 Anos'] = False
  shares['Payout Saudavel nos Ultimos 5 Anos'] = False

def fill_score(shares):
  shares['Bazin Score'] += (shares['Preço Justo (Bazin)'] > Decimal(1.5) * shares['Cotação']).astype(int)
  shares['Bazin Score'] += (shares['Dividend Yield'] > 0.06).astype(int)
  shares['Bazin Score'] += ((shares['Dívida Bruta/Patrimônio']).astype(float) < 0.5).astype(int)

# Mostra quais filtros a ação passou para pontuar seu Bazin Score
def fill_score_explanation(shares):
  shares['Preço Justo (Bazin) > 1.5 * Cotação'] = shares['Preço Justo (Bazin)'] > Decimal(1.5) * shares['Cotação']
  shares['Dividend Yield > 0.06'] = shares['Dividend Yield'] > 0.06
  shares['Dívida Bruta/Patrimônio < 0.5'] = (shares['Dívida Bruta/Patrimônio']).astype(float) < 0.5 # https://www.investimentonabolsa.com/2015/07/saiba-analisar-divida-das-empresas.html https://www.sunoresearch.com.br/artigos/5-indicadores-para-avaliar-solidez-de-uma-empresa/

def fill_special_infos(shares):
  for index in range(len(shares)):
    ticker = shares.index[index]
    shares['Media de Dividend Yield dos Últimos 5 anos'][index] = infos[ticker]['ultimos_dy']
    shares['Bazin Score'][index] += int(infos[ticker]['ultimos_dy'] > 0.05)
    shares['Dividendos > 5% na média dos últimos 5 anos'][index] = infos[ticker]['ultimos_dy'] > 0.05
    shares['Bazin Score'][index] += int(infos[ticker]['constante'])
    shares['Dividendos Constantes Ultimos 5 Anos'][index] = infos[ticker]['constante']
    shares['Bazin Score'][index] += int(infos[ticker]['crescente'])
    shares['Dividendos Crescentes Ultimos 5 Anos'][index] = infos[ticker]['crescente']
    shares['Bazin Score'][index] += int(infos[ticker]['healthy_payout'])
    shares['Payout Saudavel nos Ultimos 5 Anos'][index] = infos[ticker]['healthy_payout']
  return shares

# Reordena a tabela para mostrar a Cotação, o Valor Intríseco e o Bazin Score como primeiras colunass
def reorder_columns(shares):
  columns = ['Ranking (Bazin)', 'Cotação', 'Preço Justo (Bazin)', 'Bazin Score', 'Preço Justo (Bazin) / Cotação', 'Media de Dividend Yield dos Últimos 5 anos', 'Dividend Yield']
  return shares[columns + [col for col in shares.columns if col not in tuple(columns)]]

# Get the current_year integer value, for example: 2020
def current_year():
  return int(time.strftime("%Y"))

# Copia o result no formato Markdown (Git :D)
def copy(shares):
  subprocess.run('pbcopy', universal_newlines=True, input=shares.to_markdown())

# python3 bazin.py "{ 'year': 2015 }"
if __name__ == '__main__':  
  year = current_year()
  if len(sys.argv) > 1:
    year = int(eval(sys.argv[1])['year'])
  
  shares = populate_shares(year)
  
  shares.sort_values(by=['Bazin Score', 'Media de Dividend Yield dos Últimos 5 anos'], ascending=[False, False], inplace=True)
  
  shares['Ranking (Bazin)'] = range(1, len(shares) + 1)
  
  print(shares)
  copy(shares)
  
  if year != current_year():
    backtest.run_all(fundamentus.start_date(year), list(shares.index[:20]))