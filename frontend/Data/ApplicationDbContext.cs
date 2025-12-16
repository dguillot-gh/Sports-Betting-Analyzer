using Microsoft.EntityFrameworkCore;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Data
{
    public class ApplicationDbContext : DbContext
    {
        public ApplicationDbContext(DbContextOptions<ApplicationDbContext> options)
            : base(options)
        {
        }

        public DbSet<HistoricalBet> HistoricalBets { get; set; }
        public DbSet<TeamStats> TeamStats { get; set; }
        public DbSet<HistoricalGameResult> HistoricalGameResults { get; set; }
        public DbSet<PlayerStats> PlayerStats { get; set; }

        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            base.OnModelCreating(modelBuilder);

            modelBuilder.Entity<HistoricalBet>(entity =>
            {
                entity.HasKey(e => e.Id);
                entity.Property(e => e.Team1).HasMaxLength(200);
                entity.Property(e => e.Team2).HasMaxLength(200);
                entity.Property(e => e.PlayerName).HasMaxLength(200);
                entity.Property(e => e.BetType).HasMaxLength(50);
                entity.Property(e => e.Sport).HasMaxLength(50);
                entity.Property(e => e.Recommendation).HasMaxLength(50);
                entity.HasIndex(e => e.AnalyzedAt);
                entity.HasIndex(e => e.Sport);
            });

            modelBuilder.Entity<TeamStats>(entity =>
            {
                entity.HasKey(e => e.Id);
                entity.Property(e => e.TeamName).HasMaxLength(200);
                entity.Property(e => e.Sport).HasMaxLength(50);
                entity.Property(e => e.Source).HasMaxLength(200);
                entity.HasIndex(e => new { e.TeamName, e.Sport });
            });

            modelBuilder.Entity<HistoricalGameResult>(entity =>
            {
                entity.HasKey(e => e.Id);
                entity.Property(e => e.Sport).HasMaxLength(50);
                entity.Property(e => e.Team1).HasMaxLength(200);
                entity.Property(e => e.Team2).HasMaxLength(200);
                entity.Property(e => e.Season).HasMaxLength(20);
                entity.HasIndex(e => new { e.Sport, e.GameDate });
                entity.HasIndex(e => new { e.Team1, e.Team2, e.GameDate });
            });

            modelBuilder.Entity<PlayerStats>(entity =>
            {
                entity.HasKey(e => e.Id);
                entity.Property(e => e.PlayerName).HasMaxLength(200);
                entity.Property(e => e.Sport).HasMaxLength(50);
                entity.Property(e => e.Team).HasMaxLength(200);
                entity.Property(e => e.Position).HasMaxLength(50);
                entity.Property(e => e.Source).HasMaxLength(200);
                entity.HasIndex(e => new { e.PlayerName, e.Sport });
            });
        }
    }
}

