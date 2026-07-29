"""
Validation des données historiques.
Vérifie que les données sont réelles et complètes.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class DataValidator:
    """
    Valide les données historiques pour le backtesting.
    
    Vérifications:
    - Données complètes (pas de trous)
    - Prix réalistes (pas de spikes aberrants)
    - Volume cohérent
    - Timestamps valides
    - Pas de données dupliquées
    """
    
    def __init__(self, strict_mode: bool = True):
        self.strict_mode = strict_mode
        self.warnings: List[str] = []
        self.errors: List[str] = []
    
    def validate(self, data: pd.DataFrame, pair: str = "UNKNOWN") -> Tuple[bool, Dict]:
        """
        Valide un DataFrame de données.
        
        Returns:
            (is_valid, report)
        """
        self.warnings = []
        self.errors = []
        
        report = {
            'pair': pair,
            'total_rows': len(data),
            'start_date': str(data['timestamp'].min()) if 'timestamp' in data.columns else 'N/A',
            'end_date': str(data['timestamp'].max()) if 'timestamp' in data.columns else 'N/A',
            'checks': {}
        }
        
        # Vérifications
        self._check_columns(data)
        self._check_completeness(data)
        self._check_price_validity(data, pair)
        self._check_volume(data)
        self._check_timestamps(data)
        self._check_duplicates(data)
        self._check_data_freshness(data)
        
        # Résumé
        report['errors'] = self.errors
        report['warnings'] = self.warnings
        report['is_valid'] = len(self.errors) == 0
        report['quality_score'] = self._calculate_quality_score(data)
        
        if self.errors:
            logger.error(f"Validation FAILED for {pair}: {len(self.errors)} errors")
        elif self.warnings:
            logger.warning(f"Validation passed with {len(self.warnings)} warnings for {pair}")
        else:
            logger.info(f"Validation PASSED for {pair}: {len(data)} rows, quality={report['quality_score']:.0%}")
        
        return report['is_valid'], report
    
    def _check_columns(self, data: pd.DataFrame):
        """Vérifie les colonnes requises."""
        required = ['timestamp', 'open', 'high', 'low', 'close']
        missing = [col for col in required if col not in data.columns]
        
        if missing:
            self.errors.append(f"Colonnes manquantes: {missing}")
        else:
            self._record_check('columns', True, f"Colonnes OK: {list(data.columns)}")
    
    def _check_completeness(self, data: pd.DataFrame):
        """Vérifie les données manquantes."""
        null_counts = data[['open', 'high', 'low', 'close']].isnull().sum()
        total_nulls = null_counts.sum()
        
        if total_nulls > 0:
            null_pct = total_nulls / (len(data) * 4) * 100
            if null_pct > 5:
                self.errors.append(f"Trop de données manquantes: {null_pct:.1f}%")
            else:
                self.warnings.append(f"Données manquantes: {null_pct:.1f}%")
        
        self._record_check('completeness', total_nulls == 0, f"Nulls: {total_nulls}")
    
    def _check_price_validity(self, data: pd.DataFrame, pair: str):
        """Vérifie que les prix sont réalistes."""
        # Vérifier les prix négatifs
        if (data[['open', 'high', 'low', 'close']] < 0).any().any():
            self.errors.append("Prix négatifs détectés!")
        
        # Vérifier high >= low
        invalid_hl = data[data['high'] < data['low']]
        if len(invalid_hl) > 0:
            self.errors.append(f"high < low dans {len(invalid_hl)} lignes")
        
        # Vérifier high >= open et high >= close
        invalid_ho = data[data['high'] < data['open']]
        invalid_hc = data[data['high'] < data['close']]
        if len(invalid_ho) > 0 or len(invalid_hc) > 0:
            self.warnings.append(f"high < open/close dans quelques lignes")
        
        # Détecter les spikes (variations > 10% en 1 barre)
        returns = data['close'].pct_change().abs()
        spikes = returns[returns > 0.10]
        if len(spikes) > 0:
            self.warnings.append(f"Possibles spikes détectés: {len(spikes)} barres avec >10% variation")
        
        # Vérifier les prix à 0
        if (data[['open', 'high', 'low', 'close']] == 0).any().any():
            self.errors.append("Prix à 0 détectés!")
        
        self._record_check('price_validity', len(self.errors) == 0, 
                          f"Prix min={data['low'].min():.5f} max={data['high'].max():.5f}")
    
    def _check_volume(self, data: pd.DataFrame):
        """Vérifie le volume."""
        if 'volume' not in data.columns:
            self.warnings.append("Pas de colonne volume")
            return
        
        zero_volume = (data['volume'] == 0).sum()
        if zero_volume > len(data) * 0.5:
            self.warnings.append(f"{zero_volume} barres sans volume ({zero_volume/len(data):.0%})")
        
        self._record_check('volume', True, f"Volume moyen: {data['volume'].mean():,.0f}")
    
    def _check_timestamps(self, data: pd.DataFrame):
        """Vérifie les timestamps."""
        if 'timestamp' not in data.columns:
            return
        
        # Vérifier l'ordre chronologique
        is_sorted = data['timestamp'].is_monotonic_increasing
        if not is_sorted:
            self.errors.append("Timestamps non ordonnés chronologiquement!")
        
        # Vérifier les gaps
        time_diffs = data['timestamp'].diff().dropna()
        median_diff = time_diffs.median()
        
        # Trop de gaps
        large_gaps = time_diffs[time_diffs > median_diff * 3]
        if len(large_gaps) > 0:
            self.warnings.append(f"{len(large_gaps)} gaps temporels détectés")
        
        self._record_check('timestamps', is_sorted, 
                          f"Période: {data['timestamp'].min()} → {data['timestamp'].max()}")
    
    def _check_duplicates(self, data: pd.DataFrame):
        """Vérifie les doublons."""
        if 'timestamp' in data.columns:
            duplicates = data.duplicated(subset=['timestamp']).sum()
        else:
            duplicates = data.duplicated().sum()
        
        if duplicates > 0:
            self.warnings.append(f"{duplicates} lignes dupliquées")
        
        self._record_check('duplicates', duplicates == 0, f"Doublons: {duplicates}")
    
    def _check_data_freshness(self, data: pd.DataFrame):
        """Vérifie la fraîcheur des données."""
        if 'timestamp' not in data.columns:
            return
        
        last_date = data['timestamp'].max()
        if isinstance(last_date, str):
            last_date = pd.to_datetime(last_date)
        
        days_old = (datetime.now() - last_date).days
        
        if days_old > 365:
            self.warnings.append(f"Données anciennes: {days_old} jours")
        
        self._record_check('freshness', days_old < 30, f"Dernière donnée: {days_old} jours")
    
    def _calculate_quality_score(self, data: pd.DataFrame) -> float:
        """Calcule un score de qualité des données (0-100%)."""
        score = 100.0
        
        # Pénalités
        score -= len(self.errors) * 20
        score -= len(self.warnings) * 5
        
        # Bonus pour volume
        if 'volume' in data.columns and data['volume'].mean() > 0:
            score += 5
        
        # Bonus pour longueur
        if len(data) > 1000:
            score += 5
        
        return max(0, min(100, score))
    
    def _record_check(self, name: str, passed: bool, detail: str):
        """Enregistre le résultat d'une vérification."""
        status = "✅" if passed else "❌"
        logger.debug(f"  {status} {name}: {detail}")


def validate_historical_data(data: pd.DataFrame, pair: str, strict: bool = True) -> Tuple[bool, Dict]:
    """Fonction utilitaire pour valider les données."""
    validator = DataValidator(strict_mode=strict)
    return validator.validate(data, pair)


def get_data_quality_report(data: pd.DataFrame, pair: str) -> str:
    """Génère un rapport de qualité des données en texte."""
    validator = DataValidator(strict_mode=False)
    is_valid, report = validator.validate(data, pair)
    
    lines = [
        f"=== RAPPORT DE QUALITÉ DES DONNÉES ===",
        f"Paire: {pair}",
        f"Lignes: {report['total_rows']}",
        f"Période: {report['start_date']} → {report['end_date']}",
        f"Score qualité: {report['quality_score']:.0f}%",
        f"Valide: {'✅ OUI' if is_valid else '❌ NON'}",
        "",
    ]
    
    if report['errors']:
        lines.append("ERREURS:")
        for e in report['errors']:
            lines.append(f"  ❌ {e}")
    
    if report['warnings']:
        lines.append("AVERTISSEMENTS:")
        for w in report['warnings']:
            lines.append(f"  ⚠️ {w}")
    
    if not report['errors'] and not report['warnings']:
        lines.append("✅ Aucun problème détecté!")
    
    return "\n".join(lines)
