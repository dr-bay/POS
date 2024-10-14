from django.db import models
from django.contrib.auth.models import User

class Supplier(models.Model):
    name = models.CharField(max_length=100)
    contact_person = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    address = models.TextField()

    def __str__(self):
        return self.name

class Category(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name

class Ingredient(models.Model):
    name = models.CharField(max_length=100)
    quantity = models.FloatField()
    unit = models.CharField(max_length=20)
    reorder_point = models.FloatField()
    cost_per_unit = models.DecimalField(max_digits=10, decimal_places=2)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        return f"{self.name} ({self.quantity} {self.unit})"

class MenuItem(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    price = models.DecimalField(max_digits=6, decimal_places=2)
    misc_cost = models.DecimalField(max_digits=6, decimal_places=2, default=0)  # New field for additional costs
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    image = models.ImageField(upload_to='menu_items/', null=True, blank=True)
    is_available = models.BooleanField(default=True)

    def caluclate_cost(self):
        """Calculate the cost based on ingredients and fixed misc cost."""
        total_cost = sum(
            recipe.ingredient.cost_per_unit * recipe.quantity
            for recipe in self.recipe_items.all()
        )
        return total_cost + self.misc_cost

    def __str__(self):
        return self.name

class MenuItemComponent(models.Model):
    parent_item = models.ForeignKey(MenuItem, related_name='parent', on_delete=models.CASCADE)
    component_item = models.ForeignKey(MenuItem, related_name='component', on_delete=models.CASCADE)
    quantity = models.FloatField()

    def __str__(self):
        return f"{self.quantity}x {self.component_item.name} in {self.parent_item.name}"

class Recipe(models.Model):
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name='recipe_items')
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE)
    quantity = models.FloatField()

    class Meta:
        unique_together = ('menu_item', 'ingredient')

    def __str__(self):
        return f"{self.menu_item.name} - {self.ingredient.name}"
class Discount(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ('amount', 'Amount'),        # Fixed amount discount
        ('percentage', 'Percentage'), # Percentage discount
        ('coupon', 'Coupon'),        # Coupon code discount
    ]

    name = models.CharField(max_length=100)
    discount_type = models.CharField(max_length=10, choices=DISCOUNT_TYPE_CHOICES)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    coupon_code = models.CharField(max_length=50, unique=True, blank=True, null=True)
    start_date = models.DateTimeField(blank=True, null=True)
    end_date = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    excluded_items = models.ManyToManyField(MenuItem, blank=True)

    def is_valid(self):
        """Check if the discount is currently valid based on dates."""
        if not self.is_active:
            return False
        if self.start_date and self.start_date > timezone.now():
            return False
        if self.end_date and self.end_date < timezone.now():
            return False
        return True

    def __str__(self):
        return self.name
class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('preparing', 'Preparing'),
        ('ready', 'Ready for Pickup'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    PAYMENT_METHODS = [
        ('cash', 'Cash'),
        ('credit_card', 'Credit Card'),
        ('debit_card', 'Debit Card'),
        ('mobile_payment', 'Mobile Payment'),
        ('other', 'Other'),
    ]

    customer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='cash')
    delivery_address = models.TextField(blank=True, null=True)
    discount = models.ForeignKey(Discount, on_delete=models.SET_NULL, null=True, blank=True)
    coupon_code = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"Order #{self.id} - {self.customer.username if self.customer else 'Guest'}"

    def update_total_amount(self):
        # Calculate the subtotal for the order
        subtotal = sum(item.subtotal for item in self.items.all())
        
        # Apply discount
        discount_amount = 0
        if self.discount and self.discount.is_valid():
            # Apply discount to all items except excluded ones
            for item in self.items.all():
                if item.menu_item not in self.discount.excluded_items.all():
                    if self.discount.discount_type == 'amount':
                        discount_amount += self.discount.discount_value
                    elif self.discount.discount_type == 'percentage':
                        discount_amount += (item.price * self.discount.discount_value / 100) * item.quantity
        
        # Subtract discount from subtotal
        total = subtotal - discount_amount
        
        # Ensure the total amount does not go below zero
        self.total_amount = max(total, 0)
        self.save()

class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=1)
    price = models.DecimalField(max_digits=6, decimal_places=2)
    is_free = models.BooleanField(default=False)  # New field for free items

    @property
    def subtotal(self):
        return 0 if self.is_free else self.price * self.quantity

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
    
        # Reduce stock for each ingredient based on the quantity of this order item
        for recipe in self.menu_item.recipe_items.all():
            ingredient = recipe.ingredient
            ingredient.quantity -= recipe.quantity * self.quantity  # Adjust by quantity ordered
            ingredient.save()

        # Update total order amount
        self.order.update_total_amount()

    def __str__(self):
        return f"{self.quantity}x {self.menu_item.name}"